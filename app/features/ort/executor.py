from __future__ import annotations

import asyncio
import os
import shlex
from pathlib import Path

from app.config import settings
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


async def run_ort_command(job_id: str, command: str, work_dir: str, log_file: Path) -> int:
    tokens = _validate_command(command)
    tokens = _ensure_force_overwrite(tokens)

    env = os.environ.copy()
    env.setdefault("LC_ALL", "en_US.UTF-8")

    # Include project venv/bin so tools like python-inspector and scancode are found by ORT.
    venv_bin = Path(__file__).resolve().parent.parent.parent / ".venv" / (
        "Scripts" if os.name == "nt" else "bin"
    )
    extra_paths = [str(settings.ort_install_dir), str(settings.bin_dir)]
    if venv_bin.is_dir():
        extra_paths.append(str(venv_bin))
    env["PATH"] = os.pathsep.join(extra_paths) + os.pathsep + env.get("PATH", "")

    executable = "ort"
    if os.name == "nt":
        ort_bat = settings.ort_install_dir / "ort.bat"
        if not ort_bat.exists():
            ort_bat = settings.bin_dir / "ort.bat"
        if ort_bat.exists():
            executable = str(ort_bat)

    if tokens[0] == "ort":
        tokens[0] = executable

    spawn_tokens = tokens
    if os.name == "nt" and str(tokens[0]).lower().endswith(".bat"):
        # Batch scripts require cmd.exe invocation for consistent execution.
        spawn_tokens = ["cmd", "/c", *tokens]

    process = await asyncio.create_subprocess_exec(
        *spawn_tokens,
        cwd=work_dir,
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )

    with log_file.open("a", encoding="utf-8") as out:
        assert process.stdout is not None
        while True:
            line = await process.stdout.readline()
            if not line:
                break
            text = line.decode("utf-8", errors="replace")
            out.write(text)
            out.flush()
            await log_stream_hub.publish(job_id, {"type": "log", "line": text})

    return await process.wait()
