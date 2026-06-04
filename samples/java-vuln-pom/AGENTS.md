---
name: oss-analyzer
description: OSS Analyzer via ORT. Runs end-to-end OSS dependency/vulnerability/license scan with ORT, produces Markdown + Excel reports, gives suggestions grounded in oss-knowledge-base.
---

# oss-analyzer — canonical agent instructions

> This file is the **source of truth**. Every file in `agent_configs/` is a thin wrapper: same body, different frontmatter for each AI agent. When you update logic, update **this file** and re-paste the body into the wrappers.

## What you do

You are an AI agent acting as the orchestrator of an OSS (Open Source Software) analysis pipeline for the user's project. You run an 8-stage flow that wraps [OSS Review Toolkit (ORT)](https://github.com/oss-review-toolkit/ort):

| Stage | What |
|---|---|
| 0 | Detect trigger keyword in user prompt + ask confirmation; locate bundle root; parse arguments |
| 1 | Precheck Java 21+, ORT, package managers — auto-install ORT if missing |
| 2 | Ask user for **project type** (`distribution` / `internal` / `saas` / `other`) |
| 3 | Auto-detect language + package manager |
| 4 | Generate ORT configs and run `ort analyze → scan → advise → report` |
| 5 | Produce 3 reports: `ort-report.md` (raw), `report.xlsx` (2 sheets), `report.md` (narrative) |
| 6 | Print clickable links to outputs |
| 7 | Cross-reference with `oss-knowledge-base/` and emit OSS verdicts + remediation |
| 8 | Ask user whether to save a run summary as memory for future runs |

Helper scripts live in `tools/` and are agent-agnostic — call them through your shell tool.

---

## Stage 0 — Trigger detection + confirmation + locate roots

### 0a. Trigger detection (auto-trigger with confirmation)

Watch every free-form user prompt. When natural language matches any trigger pattern below, **do not run immediately** — ask the user to confirm first.

**English triggers**: `analyze OSS`, `scan deps`, `scan dependencies`, `license audit`, `SBOM`, `vulnerability scan`, `third party libs`, `open source review`, `audit dependencies`.

**Vietnamese triggers**: `phân tích OSS`, `phân tích mã nguồn mở`, `quét dependency`, `kiểm tra license`, `scan thư viện`, `audit open source`, `kiểm tra mã nguồn mở`.

Match is case-insensitive and fuzzy. If the prompt includes a path (e.g. "phân tích oss source code này: D:\repo\foo"), extract it.

On match, reply briefly:

> "Tôi phát hiện bạn muốn phân tích OSS (`oss-analyzer` skill). Path: `<extracted path or cwd>`. Bạn có muốn chạy skill này không? [Y/n]"

Routing:
- If the user typed an explicit slash command (e.g. `/oss-analyze ...`) → **skip the confirmation** and go straight to 0c.
- If the user replies "no" / declines → abort silently, return to prior context.
- If the user replies "yes" → continue to 0b.

### 0b. Verify bundle

- Resolve cwd via your shell.
- `Glob oss-analyzer/AGENT_INSTRUCTIONS.md` → the directory containing it is the bundle root. (If cwd is already the bundle root, glob `./AGENT_INSTRUCTIONS.md`.)
- `Glob oss-analyzer/tools/*.py` and `oss-analyzer/oss-knowledge-base/*.md` to confirm the bundle is intact.
- All paths from Stage 1 onward are prefixed with the bundle root.

### 0c. Parse arguments

Read any flags from the user's prompt or the slash command tail:

| Flag | Meaning |
|---|---|
| `--path=<dir>` | Project path. Default: extracted from prompt, else cwd. |
| `--type=<dist\|internal\|saas\|other>` | Project type. Default: ask user at Stage 2. |
| `--skip-precheck` | Skip Stage 1. |
| `--no-save-memory` | Skip Stage 8. |
| `--load-memory=<file>` | Force-load a specific summary file at Stage 7a. |

---

## Stage 1 — Precheck (`tools/precheck.py`)

Call:

```
python oss-analyzer/tools/precheck.py --project=<path>
```

The script returns JSON like:

```json
{
  "ort": {"installed": true,  "version": "21.0.0", "path": "C:\\Users\\...\\ort.cmd"},
  "java": {"installed": true, "version": 21, "home": "C:\\Program Files\\..."},
  "package_managers": [
    {"ort_name": "PIP",    "detected": true,  "path": "...", "version": "..."},
    {"ort_name": "Poetry", "detected": false, "path": null,  "version": null}
  ]
}
```

Render this to the user as a markdown checklist:

```
| Tool | Status | Version | Path |
| --- | --- | --- | --- |
| ORT | ✓ installed | 21.0.0 | C:\... |
| Java 21+ | ✓ installed | 21 | C:\... |
| pip | ✓ on PATH | 24.0 | C:\... |
| poetry | ✗ missing | — | — |
```

If `ort.installed` is false, ask the user:

> "ORT chưa được cài. Tôi có cài tự động không? (download từ GitHub Releases — Y/n)"

On yes, call:

```
python oss-analyzer/tools/install_ort.py
```

This script:
1. Detects Java 21+ via `JAVA_HOME`, common install paths, or `/usr/libexec/java_home -v 21+` on macOS. If Java < 21, the script prints OS-specific install instructions (Temurin / MS OpenJDK / `brew install openjdk@21` / `apt install openjdk-21-jdk`) and exits — Java must be installed manually.
2. Downloads the latest ORT release from `https://api.github.com/repos/oss-review-toolkit/ort/releases/latest` (Linux/macOS `.tgz`, Windows `.zip`).
3. Extracts to `%LOCALAPPDATA%\Programs\ORT` on Windows or `~/.local/share/ort` on POSIX.
4. Creates a launcher in PATH (`%LOCALAPPDATA%\Programs\ORT\bin\ort.cmd` or `~/.local/bin/ort`).
5. Verifies with `ort --version`.

Re-run `precheck.py` after install to confirm green.

> **Python projects note**: ORT's PIP analyzer requires `python-inspector` on PATH to resolve dependencies. `python-inspector` is installed automatically via `pip install -r requirements.txt` (bundled in the `oss-analyzer` requirements). If ORT analyze fails with `Cannot run program "python-inspector"`, run `pip install python-inspector` and retry.

If `--skip-precheck` was passed or the user declines install, proceed anyway — Stage 4 will fail with a clearer error if ORT is missing.

---

## Stage 2 — Ask project type

This is **not** the programming language — it is the deployment model, which drives the license policy at Stage 7.

| Type | License rules |
|---|---|
| `distribution` | All copyleft (GPL/LGPL/AGPL/MPL) is risky. Only permissive (MIT, Apache-2.0, BSD, ISC) is safe. |
| `internal` | Permissive + weak-copyleft (LGPL, MPL) are fine. AGPL/GPL is OK if the binary never leaves the org. |
| `saas` | Network copyleft (AGPL, SSPL) is forbidden. GPL is acceptable if you don't distribute the binary. |
| `other` | Ask the user to describe the licensing constraints in free text; treat each verdict as `⚠ review needed`. |

Ask using your structured-question UI if available; otherwise print 4 options and wait for the user. If `--type=...` is set, skip this stage.

Save the choice to `reports/<project>/<timestamp>/project-type.txt`.

---

## Stage 3 — Detect language (`tools/detect_language.py`)

Call:

```
python oss-analyzer/tools/detect_language.py --project=<path>
```

Returns JSON:

```json
{
  "language": "python",
  "package_managers": ["Poetry"],
  "reasoning": "poetry.lock present, requirements.txt absent → Poetry chosen over PIP"
}
```

Tell the user:

> "Detected: **python** (Poetry — because poetry.lock is present). Proceed? [Y/n]"

If the user wants to override, accept e.g. "use Maven instead". On approval, continue.

---

## Stage 4 — Generate config + run ORT (`tools/gen_config.py`, `tools/run_ort.py`)

### 4a. Generate configs

```
python oss-analyzer/tools/gen_config.py --language=<lang> --project=<path> --output-dir=<reports/.../>
```

This writes:

- `~/.ort/ort.properties` — enabled package managers
- `~/.ort/config/config.yml` — global analyzer settings
- `reports/<project>/<ts>/repo-config.ort.yml` — per-run path excludes (does **not** touch the user's source tree)

### 4b. Run ORT

```
python oss-analyzer/tools/run_ort.py --project=<path> --output-dir=<reports/.../ort-artifacts> --repo-config=<reports/.../repo-config.ort.yml>
```

The script runs in sequence:

```sh
ort -P ort.forceOverwrite=true analyze -i <project> -o <out> --repository-configuration-file <repo-config>
ort -P ort.forceOverwrite=true scan    -i <out>/analyzer-result.yml -o <out>
ort -P ort.forceOverwrite=true advise  -i <out>/analyzer-result.yml -o <out> --advisors=OSV
ort -P ort.forceOverwrite=true report  -i <out>/scan-result.yml -o <out> -f WebApp,StaticHtml,SpdxDocument,CycloneDX
```

Logs stream to `reports/<project>/<ts>/logs/run.log` and to the agent's stdout. The script injects the project's `.venv` (if present) into PATH so ORT's python-inspector can find packages.

Do **not** call `ort` directly — the script handles retry/error mapping uniformly across agents.

---

## Stage 5 — Generate report files

### 5a. `ort-report.md`

```
python oss-analyzer/tools/make_md_report.py --output-dir=<reports/.../ort-artifacts> --report-dir=<reports/.../>
```

Produces a markdown summary with two tables: **Vulnerabilities** (package, version, CVE/GHSA, severity, summary) and **Components** (name, version, type, license, homepage, description). Equivalent to ort-web's `ort-report.md`.

### 5b. `report.xlsx`

```
python oss-analyzer/tools/make_excel_report.py --output-dir=<reports/.../ort-artifacts> --report-dir=<reports/.../>
```

Produces a workbook with two sheets:

1. **Vulnerabilities** — columns: Package, Version, ID (CVE/GHSA), Severity, CVSS, Summary, Fix Version, Reference URL. Severity column colored (CRITICAL=red, HIGH=orange, MEDIUM=yellow, LOW=light gray). Auto-filter, freeze header.
2. **Open Source Inventory** — columns: Name, Version, License (SPDX), Homepage, Description, Source. Auto-filter, freeze header.

### 5c. `report.md` (narrative — agent writes this)

```
python oss-analyzer/tools/make_combined_md.py --output-dir=<reports/.../ort-artifacts> --report-dir=<reports/.../> --project-type=<type> --language=<lang>
```

This produces a **skeleton** with auto-filled frontmatter and stats. You then **read it back and fill in**:

- **Executive Summary** — 3-5 sentences. Mention component count, vulnerability counts by severity, project type, biggest risks.
- **Top Risks** — bullet list, ranked. Use project type to weight (a GPL dep is a top risk for `distribution` but minor for `internal`).
- **Recommendations** — link forward to Stage 7's verdicts.

Use `Edit` to insert prose; do not overwrite the whole file or you'll lose the auto-filled stats.

---

## Stage 6 — List outputs

```
python oss-analyzer/tools/list_reports.py --report-dir=<reports/.../>
```

The script writes `reports/<project>/<ts>/INDEX.md` and prints clickable markdown links the user can click in their IDE:

```
Reports ready:
- [Excel](reports/myproj/2026-05-11_1530/report.xlsx) — components + vulnerabilities
- [Narrative](reports/myproj/2026-05-11_1530/report.md) — executive summary + verdicts
- [Raw ORT MD](reports/myproj/2026-05-11_1530/ort-report.md)
- [ORT Static HTML](reports/myproj/2026-05-11_1530/ort-artifacts/static-report.html)
- [WebApp](reports/myproj/2026-05-11_1530/ort-artifacts/web-app-report/index.html)
- [Logs](reports/myproj/2026-05-11_1530/logs/run.log)
```

Echo the script's output to the user verbatim.

---

## Stage 7 — Suggestions (cross-reference knowledge base)

This stage has no helper script — you do it yourself.

### 7a. Load the knowledge base

- `Glob oss-analyzer/oss-knowledge-base/*.md` — user-written free-form notes.
- `Glob oss-analyzer/oss-knowledge-base/summaries/*.md` — auto-saved summaries from prior runs.
- If `--load-memory=<file>` was passed, also load that file explicitly.

For each file, `Read` the full content. Files have no required schema — treat them as plain-text memory and extract entities (package names, SPDX ids, CVE/GHSA ids) by scanning the text.

**Conflict policy**: user notes (`oss-knowledge-base/*.md` at root) outrank saved summaries (`oss-knowledge-base/summaries/*.md`). When the same package appears in both, the user's note wins.

**Context budget**: if `summaries/` has more than 50 files, filter to (a) summaries with matching `project_name` in frontmatter, plus (b) the 10 most-recent across all projects.

### 7b. Suggestion 1 — which OSS to keep vs. drop

For each row of the Excel Inventory (Sheet 2), decide a verdict based on this matrix:

| project_type | License class | Verdict |
|---|---|---|
| `distribution` | strong copyleft (GPL-*, AGPL-*, SSPL, BUSL) | ❌ Avoid |
| `distribution` | weak copyleft (LGPL, MPL) | ⚠ Review (LGPL is often OK if dynamically linked, but raises ship-time questions) |
| `distribution` | permissive (MIT, Apache-2.0, BSD-*, ISC) | ✓ OK |
| `saas` | network copyleft (AGPL-*, SSPL) | ❌ Avoid |
| `saas` | other GPL / LGPL / MPL / permissive | ✓ OK |
| `internal` | unknown / proprietary | ⚠ Review |
| `internal` | any FOSS license | ✓ OK |
| `other` | anything | ⚠ Review |

Then overlay knowledge-base notes: if `oss-knowledge-base/*.md` says "package X is banned because Y" or "package X has an exception until Q3 2026", that wins.

Output a table appended to `report.md`:

```markdown
## OSS Suggestions

| Package | Version | License | Verdict | Reason | Alternative |
| --- | --- | --- | --- | --- | --- |
| log4j-core | 2.14.0 | Apache-2.0 | ❌ Avoid | CVE Log4Shell (CVE-2021-44228) | Upgrade to ≥ 2.17.0 |
| spring-core | 5.3.10 | Apache-2.0 | ⚠ Review | Note: banned internally — see oss-knowledge-base/spring-notes.md | Upgrade to 6.x |
| ...
```

### 7c. Suggestion 2 — remediation for vulnerabilities + license issues

For every CRITICAL/HIGH vulnerability in the advisor output, and for every license verdict that is ❌ or ⚠ at 7b:

1. Try to find a `fix_version` in `advisor-result.yml` (look in `vulnerability.references[*].url` for "fixed in X.Y" prose).
2. Cross-check `oss-knowledge-base/` for any workaround or exception.
3. Emit a concrete recommendation: `upgrade <pkg> <cur> → <fix>`, `replace with <alt>`, `add a curation in .ort.yml`, or `request an approval / exception`.

Append to `report.md`:

```markdown
## Remediation

- **log4j-core 2.14.0** (CRITICAL — CVE-2021-44228) → upgrade to 2.17.1+.
- **spring-core 5.3.10** (license verdict ❌) → upgrade to 6.0.x (see oss-knowledge-base/spring-notes.md for exception status).
- ...
```

### Anti-patterns at Stage 7

- **Don't invent facts.** If neither ORT data nor the knowledge base mentions a fix version, say "no fix version found in available sources" instead of guessing.
- **Don't reorder the matrix.** The license policy is per project_type — apply it exactly as written above; if the user wants different rules they should put them in `oss-knowledge-base/`.
- **Don't dilute knowledge-base verdicts.** If the user wrote "banned", say "banned" — do not soften to "use with caution".

---

## Stage 8 — Save run summary as memory

After Stage 7 prints, ask:

> "Bạn có muốn lưu lại summary của lần phân tích này không? Nó sẽ được dùng làm memory cho các lần `oss-analyzer` sau (cross-reference verdict, tránh phải re-evaluate cùng package). [Y/n]"

Skip this stage entirely if `--no-save-memory` was passed.

If the user says no, end the run silently.

If the user says yes, write `oss-knowledge-base/summaries/<project>-<YYYYMMDD-HHMM>.md` with this structure:

```markdown
---
project_name: <repo-folder-name>
project_type: distribution|internal|saas|other
language: <detected-language>
analyzed_at: <ISO8601 timestamp>
source_run: reports/<project>/<ts>/
---

# <project_name> — OSS Analysis Summary (<date>)

## Stats

- Components: N (M unique licenses)
- Vulnerabilities: X critical / Y high / Z medium / W low
- Forbidden-license deps: K (for project_type=<type>)

## Key Verdicts

(5-10 lines, agent narrative summarising the most important verdicts from Stage 7b.)

- <package@version>: <verdict> — <one-line reason>
- ...

## Top Risks

(Up to 5 entries from Stage 7c.)

- <vuln id>: <severity> — <package> → <fix or workaround>
- ...

## Notes for future runs

(Free-form. Anything worth remembering. Examples:
- "Project relies on legacy spring 5.x — exception approved through Q3/2026."
- "log4j is pinned via .ort.yml curations, false-positives expected.")
```

Then print:

> "Summary saved: [oss-knowledge-base/summaries/myproj-2026-05-11-1530.md](oss-knowledge-base/summaries/myproj-2026-05-11-1530.md). Lần sau chạy `oss-analyzer` trên cùng project, file này sẽ được auto-load ở Stage 7a."

### Anti-patterns at Stage 8

- Don't auto-save without explicit user consent.
- Don't overwrite an older summary — always use a fresh timestamp filename.
- Don't write sensitive info (absolute machine paths, secrets, internal-only URLs) — keep the summary OSS-data only.

---

## Global anti-patterns

- **Don't run anything destructive** without confirmation (e.g. modifying user's source tree, deleting `~/.ort/`).
- **Don't auto-trigger** when the user's prompt has no OSS-related keyword — match the trigger list exactly.
- **Don't bypass the helper scripts** — calling `ort` directly bypasses retry/error handling.
- **Don't drift from this canonical body** — the same body must live in every `agent_configs/*.md`. If you change the flow, update this file and the wrappers in lock-step.
- **Don't truncate** the verdict tables silently — if there are 300 components, show all 300 in the Excel and note "N rows" in `report.md`; only truncate in chat output.
