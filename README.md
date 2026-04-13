# ORT Web

Local web GUI for [OSS Review Toolkit (ORT)](https://github.com/oss-review-toolkit/ort) — run ORT analyzer, stream logs in real-time, and browse results from your browser.

![Python](https://img.shields.io/badge/Python-3.11+-3776ab?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688?logo=fastapi&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-green)

## Features

- **One-click ORT install** — download and install ORT directly from the UI
- **Auto language detection** — detects project language (Python, Java, Go, Rust, Node.js, etc.) and auto-configures ORT
- **Smart config generation** — generates `~/.ort/config/config.yml` and `ort.properties` tailored to detected language
- **Real-time log streaming** — watch ORT output live via Server-Sent Events (SSE)
- **Job queue** — async job execution with parallel workers
- **HTML report generation** — auto-generates StaticHtml and WebApp reports after analysis
- **Result browser** — view and download ORT artifacts (YAML, JSON, HTML reports)
- **Bilingual UI** — Vietnamese and English
- **Modern SaaS UI** — clean design with Inter font, inspired by Vercel/Linear

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | [FastAPI](https://fastapi.tiangolo.com/) + [Uvicorn](https://www.uvicorn.org/) |
| Frontend | [HTMX](https://htmx.org/) + [Jinja2](https://jinja.palletsprojects.com/) |
| Database | SQLite (job persistence) |
| Real-time | Server-Sent Events (SSE) |
| Fonts | Inter + JetBrains Mono |

## Prerequisites

- **Python 3.11+**
- **Java 21+** (required by ORT)
- **ORT** — can be installed via the UI or manually

## Quick Start

### 1. Clone the repository

```bash
git clone https://github.com/tnvinh2711/ort-web.git
cd ort-web
```

### 2. Create virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate  # macOS/Linux
# .venv\Scripts\activate   # Windows
```

### 3. Install dependencies

```bash
pip3 install -e .
```

For Python project analysis support (ORT's PIP analyzer):

```bash
pip3 install python-inspector setuptools
```

### 4. Run the app

```bash
uvicorn app.main:app --reload
```

### 5. Open browser

```
http://127.0.0.1:8000
```

## Usage

### Install ORT

Click **"Install ORT"** on the Dashboard. The installer downloads the latest ORT release from GitHub and sets up the binary automatically.

Default install locations:
- **macOS**: `/opt/homebrew/bin` or `/usr/local/bin`
- **Windows**: `%LOCALAPPDATA%\Programs\ORT\bin`
- **Linux**: `~/.local/bin`

### Analyze a Project

1. Click **"Pick folder"** to select a project directory
2. Click **"Detect"** to auto-detect the programming language
3. The system auto-selects the right package managers and generates ORT config
4. Click **"Analyze"** to start

ORT will:
- Generate `~/.ort/config/config.yml` with language-specific settings
- Generate `ort.properties` with the correct package managers enabled
- Create a per-job repository config with path excludes
- Run the analysis and stream logs in real-time
- Auto-generate HTML reports on success

### Environment Setup

Visit `/setup` to:
- Detect installed package manager tools on your system
- Auto-select package managers by language
- Generate and preview `config.yml`
- Apply custom `ort.properties` configuration

## Project Structure

```
ort-web/
  app/
    main.py                  # FastAPI entry point
    config.py                # Settings and runtime directories
    models.py                # Job model and status enum
    i18n.py                  # Translation utilities
    i18n/                    # Vietnamese and English translations
    core/
      ort_registry.py        # ORT tools/plugins/config metadata
    routers/
      dashboard.py           # Main UI, job creation, ORT commands
      jobs.py                # Job detail, SSE log streaming
      setup.py               # Environment setup, config management
      results.py             # Artifact browsing and rendering
      tools.py               # ORT core tools reference
      commands.py            # ORT commands reference
      plugins.py             # ORT plugins reference
    services/
      ort_config.py          # config.yml and .ort.yml generation
      ort_properties.py      # ort.properties management
      ort_executor.py        # ORT command execution
      ort_installer.py       # ORT download and installation
      language_detector.py   # Project language detection
      job_queue.py           # Async job processing
      job_store.py           # SQLite job persistence
      log_stream.py          # SSE pub/sub for real-time logs
    templates/               # Jinja2 HTML templates
    static/                  # CSS and JavaScript
  runtime/                   # Logs, artifacts, database (gitignored)
  pyproject.toml             # Project metadata and dependencies
```

## Supported Languages

| Language | Package Managers | Definition Files |
|----------|-----------------|-----------------|
| Python | PIP, Poetry | `pyproject.toml`, `requirements.txt`, `setup.py` |
| Java | Gradle, Maven | `build.gradle`, `build.gradle.kts`, `pom.xml` |
| Kotlin | Gradle, Maven | `build.gradle.kts` |
| JavaScript / TypeScript | NPM, PNPM, Yarn | `package.json` |
| Go | GoMod | `go.mod` |
| Rust | Cargo | `Cargo.toml` |
| C# / .NET | DotNet | `.csproj`, `.sln` |
| C / C++ | Conan | `conanfile.txt` |
| Ruby | Bundler | `Gemfile` |
| PHP | Composer | `composer.json` |
| Swift | Swift PM | `Package.swift` |

## Configuration

### Auto-generated files

When you run Analyze, the following files are auto-generated:

- **`~/.ort/config/config.yml`** — global ORT configuration (enabled package managers, analyzer settings)
- **`~/.ort/ort.properties`** — package manager selection
- **`runtime/artifacts/<job_id>/repo-config.ort.yml`** — per-job path excludes

### Manual configuration

You can also manually configure ORT via the **Setup** page (`/setup`), where you can:
- Select/deselect individual package managers
- Provide custom binary paths for missing tools
- Generate and edit `config.yml`

## Cross-Platform Support

| Platform | Status |
|----------|--------|
| macOS (ARM/Intel) | Fully supported |
| Windows | Supported |
| Linux | Supported |

## License

MIT
