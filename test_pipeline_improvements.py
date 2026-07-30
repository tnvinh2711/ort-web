import asyncio
import json
import os
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import yaml

import app.features.jobs.queue as job_queue
import app.features.trivy.scanner as trivy_scanner
import app.features.ort.installer as ort_installer
import app.features.ort.executor as ort_executor
import app.features.ort.java_runtime as java_runtime
from app.config import Settings
from app.models import Job
from app.features.jobs.store import JobStore
from app.features.jobs.queue import _advise_input, _run_post_analyze_pipeline
from app.features.dashboard.router import _scan_mode_flags
from app.features.ort.env_installer import detect_install_tasks, install_environment
from app.features.ort.executor import _build_ort_env, _ort_executable_candidates
from app.features.ort.installer import (
    WINDOWS_TYPECODE_LIBMAGIC_VERSION,
    _deploy_distribution,
    _ensure_libmagic,
    _libmagic_install_command,
)
from app.features.ort.java_runtime import apply_java_runtime, resolve_java_home
from app.features.ort.config import (
    _get_swift_unresolvable_definition_file_excludes,
    generate_repo_config,
)
from app.features.ort.properties import (
    auto_generate_ort_properties,
    get_available_managers_for_language,
)
from app.features.ort.precheck import _find_swift_local_path_manifests
from app.features.analysis.markdown_report import generate_markdown_report
from app.features.analysis import vuln_summary
from app.features.analysis.vuln_summary import parse_trivy_vuln_summary
from app.features.trivy.scanner import (
    _is_swift_target,
    build_trivy_html,
    build_trivy_markdown,
    run_trivy_scan,
)


def test_gradle_cache_and_no_duplicate_warmup(tmp_path, monkeypatch):
    monkeypatch.setenv("ORT_WEB_GRADLE_USER_HOME", str(tmp_path / "cache"))
    monkeypatch.delenv("GRADLE_USER_HOME", raising=False)
    assert Settings().gradle_user_home_dir == (tmp_path / "cache").resolve()
    assert _build_ort_env()["GRADLE_USER_HOME"] == str((tmp_path / "cache").resolve())
    assert str(Path(sys.executable).parent.resolve()) in _build_ort_env()["PATH"].split(
        os.pathsep
    )

    explicit_cache = tmp_path / "existing-gradle-home"
    monkeypatch.setenv("GRADLE_USER_HOME", str(explicit_cache))
    assert _build_ort_env()["GRADLE_USER_HOME"] == str(explicit_cache)

    project = tmp_path / "gradle-project"
    project.mkdir()
    (project / "build.gradle.kts").write_text("plugins { java }", encoding="utf-8")
    wrapper = project / "gradlew"
    wrapper.write_text("#!/bin/sh\n", encoding="utf-8")
    wrapper.chmod(0o755)

    assert not any(t["label"].startswith("gradle") for t in detect_install_tasks(str(project)))
    assert "Gradle" in get_available_managers_for_language("java", str(project))


def _fake_java_home(root: Path, version: str) -> Path:
    java = root / "bin" / ("java.exe" if os.name == "nt" else "java")
    java.parent.mkdir(parents=True)
    if os.name == "nt":
        java.write_text(f'@echo off\r\necho openjdk version "{version}" 1>&2\r\n')
    else:
        java.write_text(
            f'#!/bin/sh\necho \'openjdk version "{version}"\' >&2\n',
            encoding="utf-8",
        )
        java.chmod(0o755)
    return root


def test_java_runtime_selection_is_shared_and_overridable(tmp_path):
    java21 = _fake_java_home(tmp_path / "jdk-21", "21.0.10")
    java26 = _fake_java_home(tmp_path / "jdk-26", "26.0.1")

    path_only = {"PATH": str(java21 / "bin")}
    assert resolve_java_home(path_only) == java21.resolve()

    java_home_wins = {"JAVA_HOME": str(java26), "PATH": str(java21 / "bin")}
    assert resolve_java_home(java_home_wins) == java26.resolve()

    app_override_wins = {
        "ORT_WEB_JAVA_HOME": str(java21),
        "JAVA_HOME": str(java26),
        "PATH": str(java26 / "bin"),
    }
    assert apply_java_runtime(app_override_wins) == java21.resolve()
    assert app_override_wins["JAVA_HOME"] == str(java21.resolve())
    assert app_override_wins["PATH"].split(os.pathsep)[0] == str(
        java21.resolve() / "bin"
    )


def test_macos_java_stub_resolves_real_jdk_home(tmp_path, monkeypatch):
    java21 = _fake_java_home(tmp_path / "jdk-21", "21.0.10")
    monkeypatch.setattr(java_runtime.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(java_runtime.shutil, "which", lambda *_args, **_kwargs: "/usr/bin/java")
    monkeypatch.setattr(
        java_runtime.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0,
            stdout=str(java21),
        ),
    )

    assert resolve_java_home({"PATH": "/usr/bin"}) == java21.resolve()


def test_ort_env_uses_the_same_configured_java_home(tmp_path, monkeypatch):
    java21 = _fake_java_home(tmp_path / "jdk-21", "21.0.10")
    java26 = _fake_java_home(tmp_path / "jdk-26", "26.0.1")
    monkeypatch.setenv("ORT_WEB_JAVA_HOME", str(java21))
    monkeypatch.setenv("JAVA_HOME", str(java26))

    env = _build_ort_env()
    assert env["JAVA_HOME"] == str(java21.resolve())
    assert env["PATH"].split(os.pathsep)[0] == str(java21.resolve() / "bin")


def test_ort_env_sets_configured_max_heap(monkeypatch):
    monkeypatch.setattr(
        ort_executor,
        "settings",
        replace(ort_executor.settings, ort_java_max_heap="12GB"),
    )
    monkeypatch.setenv("JAVA_OPTS", "-Dfile.encoding=UTF-8 -Xmx4g")

    java_opts = _build_ort_env()["JAVA_OPTS"]

    assert java_opts.endswith("-Xmx12g")
    assert "-Dfile.encoding=UTF-8" in java_opts


def test_analyze_environment_skips_duplicate_node_install(tmp_path, monkeypatch):
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")
    log_file = tmp_path / "install.log"
    commands = []

    async def fail_if_streamed(*args, **kwargs):
        commands.append((args, kwargs))
        return 0

    monkeypatch.setattr(
        "app.features.ort.env_installer._which",
        lambda *_commands: "/usr/local/bin/npm",
    )
    monkeypatch.setattr(
        "app.features.ort.env_installer._stream",
        fail_if_streamed,
    )

    rc = asyncio.run(
        install_environment(
            "job-1",
            str(tmp_path),
            log_file,
            node_tool_only=True,
        )
    )

    assert rc == 0
    assert commands == []
    assert "project install skipped" in log_file.read_text(encoding="utf-8")


def test_ort_executor_prefers_real_distribution_launcher():
    candidates = _ort_executable_candidates()
    assert candidates
    assert ".ort-dist" in candidates[0].parts
    assert candidates[0].parent.name == "bin"


def test_installed_ort_launcher_respects_existing_java_home(tmp_path):
    source = tmp_path / "source"
    source_bin = source / "bin"
    source_bin.mkdir(parents=True)
    source_launcher = source_bin / ("ort.bat" if os.name == "nt" else "ort")
    source_launcher.write_text("echo ORT\n", encoding="utf-8")
    source_launcher.chmod(0o755)
    java21 = _fake_java_home(tmp_path / "jdk-21", "21.0.10")

    launcher, _ = _deploy_distribution(source, tmp_path / "target", java21)
    content = launcher.read_text(encoding="utf-8")
    if os.name == "nt":
        assert "if not defined JAVA_HOME" in content
    else:
        assert '${JAVA_HOME:=' in content
    assert str(java21) in content


def test_scan_modes_are_mutually_exclusive():
    assert _scan_mode_flags("vulnerability", "on", "on") == (True, False)
    assert _scan_mode_flags("license", "on", "on") == (False, True)
    assert _scan_mode_flags("full", None, None) == (True, True)


def test_node_repo_config_excludes_generated_and_agent_worktrees(tmp_path):
    project = tmp_path / "node-project"
    project.mkdir()
    (project / ".git").mkdir()
    config_path = tmp_path / "node-repo-config.yml"

    generate_repo_config("typescript", config_path, project_path=str(project))

    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    patterns = {entry["pattern"] for entry in data["excludes"]["paths"]}
    assert {
        "**/node_modules/**",
        "**/.next/**",
        "**/.turbo/**",
        "**/dist/**",
        "**/out/**",
        "**/.claude/worktrees/**",
        "**/.codex/worktrees/**",
    }.issubset(patterns)


def test_libmagic_install_commands_for_macos_and_windows(monkeypatch):
    monkeypatch.setattr(
        ort_installer.shutil,
        "which",
        lambda command: "/opt/homebrew/bin/brew" if command == "brew" else None,
    )
    assert _libmagic_install_command("Darwin") == [
        "/opt/homebrew/bin/brew",
        "install",
        "libmagic",
    ]

    windows_command = _libmagic_install_command("Windows")
    assert windows_command == [
        ort_installer.sys.executable,
        "-m",
        "pip",
        "install",
        "--upgrade",
        "--only-binary=:all:",
        f"typecode-libmagic=={WINDOWS_TYPECODE_LIBMAGIC_VERSION}",
    ]
    assert _libmagic_install_command("Linux") is None


def test_ensure_libmagic_skips_install_when_already_available(monkeypatch):
    messages = []

    async def log(message):
        messages.append(message)

    monkeypatch.setattr(
        ort_installer,
        "_libmagic_is_available",
        lambda: (True, "545"),
    )
    monkeypatch.setattr(
        ort_installer,
        "_libmagic_install_command",
        lambda _system: (_ for _ in ()).throw(AssertionError("must not install")),
    )

    assert asyncio.run(_ensure_libmagic(log))
    assert any("libmagic found" in message for message in messages)


def test_ensure_libmagic_installs_and_rechecks_on_windows(monkeypatch):
    messages = []
    commands = []
    checks = iter([(False, "NoMagicLibError"), (True, "539")])

    class EmptyAsyncOutput:
        def __aiter__(self):
            return self

        async def __anext__(self):
            raise StopAsyncIteration

    class SuccessfulProcess:
        stdout = EmptyAsyncOutput()
        returncode = 0

        async def wait(self):
            return self.returncode

    async def fake_create_subprocess_exec(*command, **_kwargs):
        commands.append(list(command))
        return SuccessfulProcess()

    async def log(message):
        messages.append(message)

    monkeypatch.setattr(ort_installer.platform, "system", lambda: "Windows")
    monkeypatch.setattr(
        ort_installer,
        "_libmagic_is_available",
        lambda: next(checks),
    )
    monkeypatch.setattr(
        ort_installer.asyncio,
        "create_subprocess_exec",
        fake_create_subprocess_exec,
    )

    assert asyncio.run(_ensure_libmagic(log))
    assert commands == [_libmagic_install_command("Windows")]
    assert any("installed successfully" in message for message in messages)


def test_wrapper_only_gradle_is_written_to_ort_properties(tmp_path, monkeypatch):
    project = tmp_path / "gradle-project"
    project.mkdir()
    (project / "gradlew").write_text("#!/bin/sh\n", encoding="utf-8")
    properties_path = tmp_path / "ort.properties"

    monkeypatch.setattr(
        "app.features.ort.properties.shutil.which",
        lambda _command: None,
    )
    monkeypatch.setattr(
        "app.features.ort.properties.get_ort_properties_path",
        lambda: properties_path,
    )
    managers = get_available_managers_for_language("java", str(project))
    auto_generate_ort_properties("java", project_path=str(project))

    assert managers == ["Gradle"]
    assert "ort.analyzer.enabledPackageManagers=Gradle" in properties_path.read_text(
        encoding="utf-8"
    )


def test_nested_swift_manifests_are_resolved_but_build_cache_is_pruned(tmp_path):
    (tmp_path / "Package.swift").write_text("", encoding="utf-8")
    nested = tmp_path / "LocalPackages" / "NetworkKit"
    nested.mkdir(parents=True)
    (nested / "Package.swift").write_text("", encoding="utf-8")
    generated = tmp_path / ".build" / "checkouts" / "Dependency"
    generated.mkdir(parents=True)
    (generated / "Package.swift").write_text("", encoding="utf-8")

    swift_tasks = [
        t for t in detect_install_tasks(str(tmp_path))
        if t["project_cmd"][:3] == ["swift", "package", "resolve"]
    ]
    assert {Path(t["cwd"]) for t in swift_tasks} == {tmp_path, nested}
    assert all(t["optional"] for t in swift_tasks)
    assert _is_swift_target(str(tmp_path))

    checkout_only = tmp_path / "checkout-only"
    checkout_manifest = checkout_only / ".build" / "checkouts" / "Dependency"
    checkout_manifest.mkdir(parents=True)
    (checkout_manifest / "Package.swift").write_text("", encoding="utf-8")
    assert not _is_swift_target(str(checkout_only))

    carthage_only = tmp_path / "carthage-only"
    carthage_only.mkdir()
    (carthage_only / "Cartfile.resolved").write_text(
        "github \"example/dependency\" \"1.0.0\"",
        encoding="utf-8",
    )
    assert _is_swift_target(str(carthage_only))


def test_swift_repo_config_skips_build_checkouts_only_for_git_worktrees(tmp_path):
    git_project = tmp_path / "git-project"
    git_project.mkdir()
    (git_project / ".git").mkdir()
    git_config = tmp_path / "git-repo-config.yml"

    generate_repo_config("swift", git_config, project_path=str(git_project))
    git_data = yaml.safe_load(git_config.read_text(encoding="utf-8"))

    assert git_data["analyzer"]["skip_excluded"] is True
    assert {
        entry["pattern"] for entry in git_data["excludes"]["paths"]
    } == {"**/.build/**"}

    archive_project = tmp_path / "archive-project"
    archive_project.mkdir()
    archive_config = tmp_path / "archive-repo-config.yml"
    generate_repo_config("swift", archive_config, project_path=str(archive_project))

    assert yaml.safe_load(archive_config.read_text(encoding="utf-8")) == {}


def test_swift_repo_config_skips_only_unresolvable_definition_files(tmp_path):
    project = tmp_path / "swift-project"
    project.mkdir()
    (project / ".git").mkdir()

    local_package = project / "LocalPackages" / "PaymentKit"
    local_package.mkdir(parents=True)
    (local_package / "Package.swift").write_text(
        '.package(path: "../AnalyticsKit")', encoding="utf-8"
    )
    (local_package / "Sources.swift").write_text("// first-party source", encoding="utf-8")

    pods = project / "Examples"
    pods.mkdir()
    (pods / "Podfile").write_text("platform :ios, '15.0'", encoding="utf-8")

    valid_pods = project / "App"
    valid_pods.mkdir()
    (valid_pods / "Podfile").write_text("platform :ios, '15.0'", encoding="utf-8")
    (valid_pods / "Podfile.lock").write_text("PODS:", encoding="utf-8")

    patterns = {
        entry["pattern"]
        for entry in _get_swift_unresolvable_definition_file_excludes(str(project))
    }
    assert patterns == {"LocalPackages/PaymentKit/Package.swift", "Examples/Podfile"}

    config_path = tmp_path / "repo-config.yml"
    generate_repo_config("swift", config_path, project_path=str(project))
    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert patterns.issubset({entry["pattern"] for entry in data["excludes"]["paths"]})


def test_swift_local_path_precheck_ignores_build_checkouts(tmp_path):
    local_package = tmp_path / "LocalPackages" / "PaymentKit"
    local_package.mkdir(parents=True)
    manifest = local_package / "Package.swift"
    manifest.write_text(
        '.package(name: "Analytics", path: "../AnalyticsKit")',
        encoding="utf-8",
    )

    checkout = tmp_path / ".build" / "checkouts" / "Dependency"
    checkout.mkdir(parents=True)
    (checkout / "Package.swift").write_text(
        '.package(path: "../Generated")',
        encoding="utf-8",
    )

    assert _find_swift_local_path_manifests(str(tmp_path)) == [manifest]


def test_markdown_report_uses_scancode_license_for_swift_package(tmp_path):
    package_id = "Swift::github.com/apple/swift-nio:2.28.0"
    provenance = {"vcs_info": {"type": "Git", "url": "https://example.test/nio.git"}}
    (tmp_path / "advisor-result.yml").write_text(
        yaml.safe_dump(
            {
                "analyzer": {
                    "result": {
                        "projects": [],
                        "packages": [{"id": package_id, "declared_licenses": []}],
                    }
                },
                "scanner": {
                    "provenances": [{"id": package_id, "package_provenance": provenance}],
                    "scan_results": [
                        {
                            "provenance": provenance,
                            "summary": {"licenses": [{"license": "Apache-2.0"}]},
                        }
                    ],
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    report = generate_markdown_report(tmp_path, markdown_reports_dir=tmp_path)
    assert report is not None
    assert "detected: Apache-2.0" in report.read_text(encoding="utf-8")


def test_advise_uses_scan_result_only_after_success(tmp_path):
    analyzer = tmp_path / "analyzer-result.yml"
    scan = tmp_path / "scan-result.yml"
    analyzer.write_text("analyzer: {}", encoding="utf-8")
    assert _advise_input(analyzer, scan, 0) == analyzer
    scan.write_text("scanner: {}", encoding="utf-8")
    assert _advise_input(analyzer, scan, 0) == scan
    assert _advise_input(analyzer, scan, 1) == analyzer


def test_trivy_vulnerability_summary_counts_each_severity(tmp_path, monkeypatch):
    artifact_dir = tmp_path / "artifacts"
    result_dir = artifact_dir / "job"
    result_dir.mkdir(parents=True)
    (result_dir / "trivy-result.json").write_text(
        json.dumps(
            {
                "Results": [
                    {
                        "Vulnerabilities": [
                            {"VulnerabilityID": "CVE-1", "Severity": "CRITICAL"},
                            {"VulnerabilityID": "CVE-2", "Severity": "HIGH"},
                            {"VulnerabilityID": "CVE-3", "Severity": "MEDIUM"},
                            {"VulnerabilityID": "CVE-4", "Severity": "LOW"},
                            {"VulnerabilityID": "CVE-5", "Severity": "UNKNOWN"},
                        ]
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(vuln_summary, "settings", SimpleNamespace(artifacts_dir=artifact_dir))
    parse_trivy_vuln_summary.cache_clear()

    assert parse_trivy_vuln_summary("job") == {
        "critical": 1,
        "high": 1,
        "medium": 1,
        "low": 1,
        "unknown": 1,
        "total": 5,
    }


def test_job_store_persists_trivy_summary_and_scancode_choice(tmp_path):
    store = JobStore(tmp_path / "jobs.sqlite3")
    store.initialize()
    job = Job(
        job_id="job",
        name="Trivy Scan sample",
        command="__trivy_scan__::/tmp/sample",
        work_dir="/tmp/sample",
        language="en",
        log_file="/tmp/job.log",
        created_at=Job.now_iso(),
        scancode_enabled=False,
        analysis_enabled=False,
        trivy_vuln_summary_json='{"critical": 1, "total": 1}',
    )
    store.create_job(job)

    loaded = store.get_job("job")
    assert loaded is not None
    assert loaded.scancode_enabled is False
    assert loaded.analysis_enabled is False
    assert loaded.trivy_vuln_summary_json == '{"critical": 1, "total": 1}'


def test_swift_pipeline_runs_scancode_and_advises_from_scan(tmp_path, monkeypatch):
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    analyzer = output_dir / "analyzer-result.yml"
    analyzer.write_text("analyzer: {}", encoding="utf-8")
    commands = []

    async def fake_run(_job_id, command, _work_dir, _log_file):
        commands.append(command)
        if " scan " in command:
            (output_dir / "scan-result.yml").write_text("scanner: {}", encoding="utf-8")
        if " advise " in command:
            (output_dir / "advisor-result.yml").write_text("advisor: {}", encoding="utf-8")
        return 0

    monkeypatch.delenv("ORT_WEB_ENABLE_SCAN", raising=False)
    monkeypatch.setattr(job_queue, "_extract_output_dir", lambda _command: output_dir)
    monkeypatch.setattr(job_queue, "run_ort_command", fake_run)
    monkeypatch.setattr(job_queue.shutil, "which", lambda *_args, **_kwargs: "/venv/bin/scancode")
    monkeypatch.setattr(job_queue, "_heal_scancode_cache", lambda *_args: asyncio.sleep(0))
    monkeypatch.setattr(job_queue, "_log_info", lambda *_args: asyncio.sleep(0))
    monkeypatch.setattr(job_queue, "_create_analyzer_html_aliases", lambda _path: [])
    monkeypatch.setattr(job_queue, "generate_component_inventory_csv", lambda _path: None)
    monkeypatch.setattr(
        job_queue, "_generate_markdown_report_for_job", lambda *_args, **_kwargs: asyncio.sleep(0)
    )
    monkeypatch.setattr(job_queue, "parse_vuln_summary", lambda _job_id: None)

    job = SimpleNamespace(
        job_id="job",
        command=f"ort analyze -i {tmp_path} -o {output_dir}",
        work_dir=str(tmp_path),
        detected_language="swift",
        vuln_summary_json=None,
    )
    assert asyncio.run(_run_post_analyze_pipeline(job, tmp_path / "job.log")) == 0
    assert "--scanners ScanCode" in commands[0]
    assert "--package-types" not in commands[0]
    assert f"-i {output_dir / 'scan-result.yml'}" in commands[1]


def test_swift_pipeline_falls_back_to_analyzer_when_scan_fails(tmp_path, monkeypatch):
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    analyzer = output_dir / "analyzer-result.yml"
    analyzer.write_text("analyzer: {}", encoding="utf-8")
    commands = []

    async def fake_run(_job_id, command, _work_dir, _log_file):
        commands.append(command)
        return 1 if " scan " in command else 0

    monkeypatch.delenv("ORT_WEB_ENABLE_SCAN", raising=False)
    monkeypatch.setattr(job_queue, "_extract_output_dir", lambda _command: output_dir)
    monkeypatch.setattr(job_queue, "run_ort_command", fake_run)
    monkeypatch.setattr(job_queue.shutil, "which", lambda *_args, **_kwargs: "/venv/bin/scancode")
    monkeypatch.setattr(job_queue, "_heal_scancode_cache", lambda *_args: asyncio.sleep(0))
    monkeypatch.setattr(job_queue, "_log_info", lambda *_args: asyncio.sleep(0))
    monkeypatch.setattr(job_queue, "generate_component_inventory_csv", lambda _path: None)
    monkeypatch.setattr(
        job_queue, "_generate_markdown_report_for_job", lambda *_args, **_kwargs: asyncio.sleep(0)
    )
    monkeypatch.setattr(job_queue, "parse_vuln_summary", lambda _job_id: None)

    job = SimpleNamespace(
        job_id="job",
        command=f"ort analyze -i {tmp_path} -o {output_dir}",
        work_dir=str(tmp_path),
        detected_language="swift",
        vuln_summary_json=None,
    )
    assert asyncio.run(_run_post_analyze_pipeline(job, tmp_path / "job.log")) == 0
    assert f"-i {analyzer}" in commands[1]


def test_scancode_toggle_can_skip_swift_license_scan(tmp_path, monkeypatch):
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    (output_dir / "analyzer-result.yml").write_text("analyzer: {}", encoding="utf-8")
    commands = []

    async def fake_run(_job_id, command, _work_dir, _log_file):
        commands.append(command)
        if " advise " in command:
            (output_dir / "advisor-result.yml").write_text("advisor: {}", encoding="utf-8")
        return 0

    monkeypatch.setattr(job_queue, "_extract_output_dir", lambda _command: output_dir)
    monkeypatch.setattr(job_queue, "run_ort_command", fake_run)
    monkeypatch.setattr(job_queue, "_log_info", lambda *_args: asyncio.sleep(0))
    monkeypatch.setattr(job_queue, "_create_analyzer_html_aliases", lambda _path: [])
    monkeypatch.setattr(job_queue, "generate_component_inventory_csv", lambda _path: None)
    monkeypatch.setattr(
        job_queue, "_generate_markdown_report_for_job", lambda *_args, **_kwargs: asyncio.sleep(0)
    )
    monkeypatch.setattr(job_queue, "parse_vuln_summary", lambda _job_id: None)

    job = SimpleNamespace(
        job_id="job",
        command=f"ort analyze -i {tmp_path} -o {output_dir}",
        work_dir=str(tmp_path),
        detected_language="swift",
        scancode_enabled=False,
        vuln_summary_json=None,
    )
    assert asyncio.run(_run_post_analyze_pipeline(job, tmp_path / "job.log")) == 0
    assert not any(" scan " in command for command in commands)


def test_scancode_only_pipeline_skips_osv_advisor(tmp_path, monkeypatch):
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    (output_dir / "analyzer-result.yml").write_text("analyzer: {}", encoding="utf-8")
    commands = []

    async def fake_run(_job_id, command, _work_dir, _log_file):
        commands.append(command)
        if " scan " in command:
            (output_dir / "scan-result.yml").write_text("scanner: {}", encoding="utf-8")
        return 0

    monkeypatch.setattr(job_queue, "_extract_output_dir", lambda _command: output_dir)
    monkeypatch.setattr(job_queue, "run_ort_command", fake_run)
    monkeypatch.setattr(job_queue.shutil, "which", lambda *_args, **_kwargs: "/venv/bin/scancode")
    monkeypatch.setattr(job_queue, "_heal_scancode_cache", lambda *_args: asyncio.sleep(0))
    monkeypatch.setattr(job_queue, "_log_info", lambda *_args: asyncio.sleep(0))
    monkeypatch.setattr(job_queue, "_create_analyzer_html_aliases", lambda _path: [])
    monkeypatch.setattr(job_queue, "generate_component_inventory_csv", lambda _path: None)
    monkeypatch.setattr(
        job_queue, "_generate_markdown_report_for_job", lambda *_args, **_kwargs: asyncio.sleep(0)
    )

    job = SimpleNamespace(
        job_id="job",
        command=f"ort analyze -i {tmp_path} -o {output_dir}",
        work_dir=str(tmp_path),
        detected_language="typescript",
        analysis_enabled=False,
        scancode_enabled=True,
    )
    assert asyncio.run(_run_post_analyze_pipeline(job, tmp_path / "job.log")) == 0
    assert any(" scan " in command for command in commands)
    assert any("--package-types PROJECT" in command for command in commands)
    assert not any(" advise " in command for command in commands)


def test_trivy_reports_include_optional_license_results(tmp_path):
    security_json = tmp_path / "trivy-result.json"
    security_json.write_text(
        json.dumps(
            {
                "ArtifactName": "sample",
                "Results": [
                    {
                        "Target": "Package.resolved",
                        "Vulnerabilities": [
                            {
                                "PkgName": "swift-nio",
                                "InstalledVersion": "2.28.0",
                                "FixedVersion": "2.100.0",
                                "VulnerabilityID": "CVE-TEST",
                                "Severity": "HIGH",
                                "Title": "test vuln",
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    license_json = tmp_path / "trivy-license-result.json"
    license_json.write_text(
        json.dumps(
            {
                "Results": [
                    {
                        "Target": "Loose File License(s)",
                        "Licenses": [
                            {
                                "Name": "Apache-2.0",
                                "Category": "notice",
                                "FilePath": ".build/checkouts/swift-nio/LICENSE.txt",
                                "Confidence": 1.0,
                            }
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    md = build_trivy_markdown(security_json, tmp_path / "report.md", license_json)
    html = build_trivy_html(security_json, tmp_path / "report.html", license_json)
    assert "Licenses: 1" in md.read_text(encoding="utf-8")
    assert "Apache-2.0" in md.read_text(encoding="utf-8")
    assert "Apache-2.0" in html.read_text(encoding="utf-8")

    no_license_md = build_trivy_markdown(security_json, tmp_path / "no-license.md")
    assert "CVE-TEST" in no_license_md.read_text(encoding="utf-8")

    malformed = tmp_path / "malformed-license.json"
    malformed.write_text("not JSON", encoding="utf-8")
    malformed_md = build_trivy_markdown(
        security_json, tmp_path / "malformed-license.md", malformed
    )
    assert "CVE-TEST" in malformed_md.read_text(encoding="utf-8")


def test_trivy_swift_license_command_omits_security_severity(tmp_path, monkeypatch):
    target = tmp_path / "swift-project"
    target.mkdir()
    (target / "Package.swift").write_text("", encoding="utf-8")
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    log_file = tmp_path / "scan.log"
    calls = []

    async def fake_ensure_trivy(_log_fn):
        return tmp_path / "trivy"

    async def fake_run(tokens, _target, _env, _log_fn, _on_process_start):
        calls.append(tokens)
        output = Path(tokens[tokens.index("--output") + 1])
        output.write_text(json.dumps({"Results": []}), encoding="utf-8")
        return 0

    monkeypatch.setattr(trivy_scanner, "ensure_trivy", fake_ensure_trivy)
    monkeypatch.setattr(trivy_scanner, "_run_trivy_process", fake_run)
    monkeypatch.setattr(
        trivy_scanner,
        "settings",
        SimpleNamespace(
            trivy_cache_dir=tmp_path / "cache",
            bin_dir=tmp_path / "bin",
            trivy_scanners="vuln,secret,misconfig",
            trivy_severity="HIGH,CRITICAL",
            trivy_offline=False,
        ),
    )

    assert asyncio.run(run_trivy_scan("job", str(target), output_dir, log_file)) == 0
    assert len(calls) == 2
    security_tokens, license_tokens = calls
    assert security_tokens[security_tokens.index("--severity") + 1] == "HIGH,CRITICAL"
    assert "**/.next" in security_tokens
    assert "**/.claude/worktrees" in security_tokens
    assert "**/node_modules" in security_tokens
    assert license_tokens[license_tokens.index("--scanners") + 1] == "license"
    assert "**/.next" in license_tokens
    assert "--license-full" in license_tokens
    assert "--severity" not in license_tokens
    assert "--offline-scan" not in license_tokens
    assert "--skip-db-update" not in license_tokens


def test_trivy_license_only_skips_vulnerability_scanners(tmp_path, monkeypatch):
    target = tmp_path / "project"
    target.mkdir()
    output_dir = tmp_path / "output"
    log_file = tmp_path / "scan.log"
    calls = []

    async def fake_ensure_trivy(_log_fn):
        return tmp_path / "trivy"

    async def fake_run(tokens, _target, _env, _log_fn, _on_process_start):
        calls.append(tokens)
        output = Path(tokens[tokens.index("--output") + 1])
        output.write_text(
            json.dumps(
                {
                    "Results": [
                        {
                            "Target": "Loose File License(s)",
                            "Licenses": [{"Name": "MIT", "FilePath": "LICENSE"}],
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        return 0

    monkeypatch.setattr(trivy_scanner, "ensure_trivy", fake_ensure_trivy)
    monkeypatch.setattr(trivy_scanner, "_run_trivy_process", fake_run)
    monkeypatch.setattr(
        trivy_scanner,
        "settings",
        SimpleNamespace(
            trivy_cache_dir=tmp_path / "cache",
            bin_dir=tmp_path / "bin",
            trivy_scanners="vuln,secret,misconfig",
            trivy_severity="HIGH,CRITICAL",
            trivy_offline=False,
        ),
    )

    assert asyncio.run(
        run_trivy_scan(
            "job",
            str(target),
            output_dir,
            log_file,
            include_vulnerabilities=False,
            include_licenses=True,
        )
    ) == 0
    assert len(calls) == 1
    assert calls[0][calls[0].index("--scanners") + 1] == "license"
    assert "--severity" not in calls[0]
    assert json.loads(
        (output_dir / "trivy-result.json").read_text(encoding="utf-8")
    )["Results"] == []
    assert "MIT" in (output_dir / "trivy-report.md").read_text(encoding="utf-8")
