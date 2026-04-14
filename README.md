# ORT Web

Local web GUI for [OSS Review Toolkit (ORT)](https://github.com/oss-review-toolkit/ort) — run ORT analyzer, stream logs in real-time, and browse results from your browser.

![Python](https://img.shields.io/badge/Python-3.9+-3776ab?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688?logo=fastapi&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-green)

## Features

- **One-click ORT install** — download and install ORT directly from the UI
- **Auto language detection** — detects project language and auto-configures ORT
- **Real-time log streaming** — watch ORT output live via SSE
- **Job queue** — async job execution with parallel workers
- **HTML report generation** — auto-generates reports after analysis
- **Job history** — filter by status, language, time range with pagination
- **Bilingual UI** — Vietnamese and English
- **Modern SaaS UI** — glassmorphism design with sidebar navigation

## Quick Start

### Install

```bash
git clone https://github.com/tnvinh2711/ort-web.git
cd ort-web
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

### Run

```bash
ort-web
```

Opens browser at `http://127.0.0.1:8000` automatically.

## CLI Usage

```bash
ort-web                    # Start server + open browser
ort-web open               # Same as above
ort-web open -p 3000       # Custom port
ort-web open --reload      # Dev mode with auto-reload
ort-web update             # Check for new version + pull
ort-web update -y          # Update without confirmation
ort-web version            # Show current version
ort-web -V                 # Short version
```

### Update

When a new version is tagged on GitHub:

```bash
ort-web update
```

This will:
1. Check GitHub for the latest tag
2. `git fetch --tags` + `git checkout <tag>`
3. `pip install -e .` to install updated dependencies

## Usage

### Install ORT

On first launch, click **"Install ORT"** on the Dashboard. The installer downloads the latest ORT release from GitHub.

Default install locations:
- **macOS**: `/opt/homebrew/bin` or `/usr/local/bin`
- **Windows**: `%LOCALAPPDATA%\Programs\ORT\bin`
- **Linux**: `~/.local/bin`

### Analyze a Project

1. Click **"Pick folder"** to select a project directory
2. Language is auto-detected (Python, Java, Go, Rust, Node.js, etc.)
3. Click **"Analyze"** to start

The analysis runs inline on the dashboard with realtime log streaming. Results (artifacts) appear when complete.

### Job History

Navigate to **"Job History"** in the sidebar to browse all past jobs with:
- Text search
- Status filter (success, failed, running, etc.)
- Language filter
- Time range (24h, 7d, 30d, 90d, custom)
- Pagination (10 per page)

Click **"View results"** on any success/failed job to see logs and generated files.

## Prerequisites

- **Python 3.9+**
- **Java 21+** (required by ORT)

For Python project analysis:

```bash
pip install python-inspector setuptools
```

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | FastAPI + Uvicorn |
| Frontend | HTMX + Jinja2 |
| Database | SQLite (job persistence) |
| Real-time | Server-Sent Events (SSE) |
| CLI | argparse |

## Supported Languages

| Language | Package Managers |
|----------|-----------------|
| Python | PIP, Poetry |
| Java / Kotlin | Gradle, Maven |
| JavaScript / TypeScript | NPM, PNPM, Yarn |
| Go | GoMod |
| Rust | Cargo |
| C# / .NET | DotNet |
| C / C++ | Conan |
| Ruby | Bundler |
| PHP | Composer |
| Swift | Swift PM |

## Project Structure

```
ort-web/
  app/
    cli.py             # CLI entry point (ort-web command)
    _version.py        # Version string
    main.py            # FastAPI app
    config.py          # Settings
    models.py          # Job model
    i18n/              # Translations (vi, en)
    routers/           # Route handlers
    services/          # Business logic (queue, executor, installer)
    templates/         # Jinja2 HTML
    static/            # CSS, JS
  runtime/             # Logs, artifacts, SQLite (gitignored)
  ARCHITECTURE.md      # Detailed app flow documentation
  pyproject.toml       # Package config + CLI entry point
```

See [ARCHITECTURE.md](ARCHITECTURE.md) for detailed application flow.

## License

MIT
