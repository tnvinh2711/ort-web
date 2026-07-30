from __future__ import annotations

import asyncio
import os
import re
import shlex
import sys
from pathlib import Path

from app.config import settings
from app.features.ort.java_runtime import apply_java_runtime
from app.features.jobs.log_stream import log_stream_hub


class OrtExecutionError(RuntimeError):
    pass


def _validate_command(command: str) -> list[str]:
    tokens = shlex.split(command)
    if not tokens:
        raise OrtExecutionError("Empty command.")

    # Local safety boundary: only allow ORT CLI entrypoint.
    if tokens[0] not in {"ort"}:
        raise OrtExecutionError("Only commands starting with 'ort' are allowed.")

    return tokens


def _ensure_force_overwrite(tokens: list[str]) -> list[str]:
    """Enable overwrite behavior via ORT config property for output-producing commands."""
    if len(tokens) < 2:
        return tokens

    subcommand_index = 1
    if tokens[1] == "-P" and len(tokens) > 3:
        subcommand_index = 3
    elif tokens[1].startswith("-P=") and len(tokens) > 2:
        subcommand_index = 2

    if len(tokens) <= subcommand_index:
        return tokens

    subcommand = tokens[subcommand_index]
    output_commands = {"analyze", "scan", "evaluate", "advise", "report"}
    if subcommand not in output_commands:
        return tokens

    has_force_property = False
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token == "-P" and i + 1 < len(tokens) and tokens[i + 1].startswith("ort.forceOverwrite="):
            has_force_property = True
            break
        if token.startswith("-P=") and token[len("-P="):].startswith("ort.forceOverwrite="):
            has_force_property = True
            break
        i += 1

    if has_force_property:
        return tokens

    # ORT 83 uses configuration key ort.forceOverwrite, not --force-overwrite CLI option.
    return [tokens[0], "-P", "ort.forceOverwrite=true", *tokens[1:]]


_HEARTBEAT_INTERVAL = 60   # seconds between "still running" log lines
_READLINE_TIMEOUT   = 60   # seconds to wait for a single line before heartbeat


def _java_heap_option(value: str) -> str:
    """Return a validated -Xmx option, accepting friendly values like 12GB."""
    normalized = value.strip().lower()
    if normalized.endswith("gb"):
        normalized = normalized[:-2] + "g"
    elif normalized.endswith("mb"):
        normalized = normalized[:-2] + "m"
    if not re.fullmatch(r"[1-9]\d*[kmg]", normalized):
        raise OrtExecutionError(
            "ORT_WEB_JAVA_MAX_HEAP must be a positive size such as 8192m or 12g."
        )
    return f"-Xmx{normalized}"


def _build_ort_env() -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("LC_ALL", "en_US.UTF-8")
    # The ORT launcher consumes JAVA_OPTS. Append our value so it wins over an
    # inherited -Xmx while preserving unrelated caller-provided JVM flags.
    if settings.ort_java_max_heap:
        java_opts = env.get("JAVA_OPTS", "").strip()
        heap_opt = _java_heap_option(settings.ort_java_max_heap)
        env["JAVA_OPTS"] = f"{java_opts} {heap_opt}".strip()
    # Speed up npm installs that ORT runs internally: prefer the local cache,
    # skip network audit and funding checks, suppress interactive prompts.
    env.setdefault("NPM_CONFIG_CACHE", str(settings.npm_cache_dir))
    env.setdefault("NPM_CONFIG_PREFER_OFFLINE", "true")
    env.setdefault("NPM_CONFIG_AUDIT", "false")
    env.setdefault("NPM_CONFIG_FUND", "false")
    env.setdefault("NPM_CONFIG_PROGRESS", "false")
    # Pin Gradle's wrapper distributions, dependency cache, and Tooling API
    # downloads to stable storage shared across analyze jobs.
    env.setdefault("GRADLE_USER_HOME", str(settings.gradle_user_home_dir))

    # Resolve the directory, not the Python symlink itself. Resolving
    # ``.venv/bin/python`` first jumps to Homebrew's interpreter directory and
    # drops sibling console scripts such as ``.venv/bin/scancode`` from PATH.
    venv_bin = Path(sys.executable).parent.resolve()
    extra_paths = [str(settings.ort_install_dir), str(settings.bin_dir)]
    if venv_bin.is_dir():
        extra_paths.append(str(venv_bin))
    env["PATH"] = os.pathsep.join(extra_paths) + os.pathsep + env.get("PATH", "")
    apply_java_runtime(env)
    return env


def _ort_executable_candidates() -> list[Path]:
    """Return launchers in order, preferring the distribution's real script.

    Older generated wrapper scripts may contain an embedded JAVA_HOME. Calling
    the real launcher lets the normalized executor environment remain the
    single source of truth.
    """
    if os.name == "nt":
        return [
            settings.ort_install_dir / ".ort-dist" / "current" / "bin" / "ort.bat",
            settings.bin_dir / ".ort-dist" / "current" / "bin" / "ort.bat",
            settings.ort_install_dir / "ort.bat",
            settings.bin_dir / "ort.bat",
        ]
    return [
        settings.ort_install_dir / ".ort-dist" / "current" / "bin" / "ort",
        Path.home() / ".local" / "bin" / ".ort-dist" / "current" / "bin" / "ort",
        settings.bin_dir / ".ort-dist" / "current" / "bin" / "ort",
        settings.ort_install_dir / "ort",
        Path.home() / ".local" / "bin" / "ort",
        settings.bin_dir / "ort",
    ]


async def run_ort_command(
    job_id: str,
    command: str,
    work_dir: str,
    log_file: Path,
    *,
    on_process_start=None,
) -> int:
    """Run an ORT subprocess with a heartbeat log and hard job timeout.

    ``on_process_start`` is invoked once with the live ``asyncio.subprocess.Process``
    so the caller (the job queue) can register it for cancellation.

    If the process has not produced a line of output within ``_READLINE_TIMEOUT``
    seconds, a "[info] still running…" heartbeat is written so the UI does not
    appear frozen (common during npm/gradle dependency resolution).

    If total runtime exceeds ``settings.ort_job_timeout_seconds`` the process is
    killed and the function returns exit-code -1.
    """
    tokens = _validate_command(command)
    tokens = _ensure_force_overwrite(tokens)

    env = _build_ort_env()

    # Resolve the ORT launcher to a full path so we never accidentally exec a
    # stale system binary (e.g. an x86_64 Homebrew ort on Apple Silicon) and
    # so installs that fell back to ~/.local/bin are found even when that
    # directory is not in PATH.
    executable = next(
        (str(candidate) for candidate in _ort_executable_candidates() if candidate.exists()),
        "ort",  # fallback: let the OS resolve via PATH
    )

    if tokens[0] == "ort":
        tokens[0] = executable

    spawn_tokens = tokens
    if os.name == "nt" and str(tokens[0]).lower().endswith(".bat"):
        # Batch scripts require cmd.exe invocation for consistent execution.
        spawn_tokens = ["cmd", "/c", *tokens]
    elif os.name != "nt" and executable != "ort":
        # Run the launcher via sh to prevent ENOEXEC if the execute bit is
        # somehow missing (e.g. after reinstall on a filesystem that resets it).
        spawn_tokens = ["sh", str(tokens[0]), *tokens[1:]]

    spawn_kwargs: dict = {
        "cwd": work_dir,
        "env": env,
        "stdout": asyncio.subprocess.PIPE,
        "stderr": asyncio.subprocess.STDOUT,
    }
    # On POSIX, start a new session so we can kill the whole process group
    # (ORT spawns a Java child — terminating just the launcher leaves it running).
    if os.name != "nt":
        spawn_kwargs["start_new_session"] = True

    process = await asyncio.create_subprocess_exec(*spawn_tokens, **spawn_kwargs)

    if on_process_start is not None:
        try:
            on_process_start(process)
        except Exception:
            pass

    import time as _time
    start_time = _time.monotonic()
    timeout_secs = settings.ort_job_timeout_seconds
    last_heartbeat = start_time

    async def _write(text: str) -> None:
        pass  # filled in inside the with-block; hoisted here for scope

    with log_file.open("a", encoding="utf-8") as out:
        assert process.stdout is not None

        async def _write(text: str) -> None:  # type: ignore[no-redef]
            out.write(text)
            out.flush()
            await log_stream_hub.publish(job_id, {"type": "log", "line": text})

        if settings.ort_java_max_heap:
            await _write(
                f"[info] ORT JVM max heap: {_java_heap_option(settings.ort_java_max_heap)}\n"
            )

        while True:
            elapsed = _time.monotonic() - start_time
            if elapsed >= timeout_secs:
                await _write(
                    f"[error] Job exceeded timeout of {timeout_secs}s — killing process.\n"
                )
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
                return -1

            try:
                line = await asyncio.wait_for(
                    process.stdout.readline(),
                    timeout=_READLINE_TIMEOUT,
                )
            except asyncio.TimeoutError:
                # No output for a while — emit a heartbeat so the UI stays alive.
                now = _time.monotonic()
                if now - last_heartbeat >= _HEARTBEAT_INTERVAL:
                    elapsed_min = int(now - start_time) // 60
                    elapsed_sec = int(now - start_time) % 60
                    await _write(
                        f"[info] still running... ({elapsed_min}m {elapsed_sec}s elapsed,"
                        f" timeout in {max(0, timeout_secs - int(now - start_time))}s)\n"
                    )
                    last_heartbeat = now
                continue

            if not line:
                break
            text = line.decode("utf-8", errors="replace")
            await _write(text)
            last_heartbeat = _time.monotonic()

    return await process.wait()
