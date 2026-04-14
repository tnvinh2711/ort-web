# ORT Web

Local web GUI for [OSS Review Toolkit (ORT)](https://github.com/oss-review-toolkit/ort) — run ORT analyzer, stream logs in real-time, and browse results from your browser.

![Python](https://img.shields.io/badge/Python-3.9+-3776ab?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688?logo=fastapi&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-green)

## Screenshots

| Dashboard | Job History | Job Detail |
|-----------|-------------|------------|
| ![Dashboard](docs/screenshots/dashboard.png) | ![Job History](docs/screenshots/job-history.png) | ![Job Detail](docs/screenshots/job-detail.png) |

## Features

- **One-click ORT install** — download and install ORT directly from the UI
- **Auto language detection** — detects project language and auto-configures ORT
- **Real-time log streaming** — watch ORT output live via SSE
- **Job queue** — async job execution with parallel workers
- **HTML report generation** — auto-generates reports after analysis
- **Job history** — filter by status, language, time range with pagination
- **Bilingual UI** — Vietnamese and English
- **Modern SaaS UI** — glassmorphism design with sidebar navigation

## Prerequisites

| Requirement | Version | Notes |
|-------------|---------|-------|
| Python | 3.9+ | |
| Java | 21+ | Required by ORT |
| Git | any | For `ort-web update` |

For Python project analysis, also install:

```bash
pip3 install python-inspector setuptools
```

---

## Installation

### macOS

```bash
git clone https://github.com/tnvinh2711/ort-web.git
cd ort-web
python3 -m venv .venv
source .venv/bin/activate
pip3 install -e .
```

Create a global symlink so `ort-web` works from anywhere:

```bash
# Apple Silicon (M1/M2/M3)
ln -sf "$PWD/.venv/bin/ort-web" /opt/homebrew/bin/ort-web

# Intel Mac
ln -sf "$PWD/.venv/bin/ort-web" /usr/local/bin/ort-web
```

### Linux

```bash
git clone https://github.com/tnvinh2711/ort-web.git
cd ort-web
python3 -m venv .venv
source .venv/bin/activate
pip3 install -e .
```

Create a global symlink:

```bash
ln -sf "$PWD/.venv/bin/ort-web" ~/.local/bin/ort-web
```

Make sure `~/.local/bin` is in your PATH (add to `~/.bashrc` or `~/.zshrc` if needed):

```bash
export PATH="$HOME/.local/bin:$PATH"
```

For the folder picker dialog on Linux, install one of:

```bash
sudo apt install zenity      # GNOME / Ubuntu
sudo dnf install zenity      # Fedora
sudo pacman -S kdialog       # KDE / Arch
```

### Windows

```cmd
git clone https://github.com/tnvinh2711/ort-web.git
cd ort-web
python -m venv .venv
.venv\Scripts\activate
pip3 install -e .
```

Run without activating venv using the included launcher:

```cmd
ort-web.bat
```

Or add the venv Scripts folder to your PATH permanently:

1. Open **System Properties** → **Advanced** → **Environment Variables**
2. Under **User variables**, select `Path` → **Edit** → **New**
3. Add the full path to `.venv\Scripts` (e.g. `C:\Users\you\ort-web\.venv\Scripts`)
4. Click OK, restart terminal

Then run:

```cmd
ort-web
```

---

## Running

### macOS / Linux

```bash
ort-web            # Start server + open browser
ort-web open       # Same as above
ort-web open -p 3000       # Custom port
ort-web open --reload      # Dev mode with auto-reload
ort-web update             # Check for new version + pull
ort-web update -y          # Update without confirmation
ort-web version            # Show current version
ort-web -V                 # Short version flag
```

### Windows

```cmd
ort-web.bat                    # Start server + open browser
ort-web.bat open               # Same as above
ort-web.bat open -p 3000       # Custom port
ort-web.bat open --reload      # Dev mode with auto-reload
ort-web.bat update             # Check for new version + pull
ort-web.bat update -y          # Update without confirmation
ort-web.bat version            # Show current version
```

If `ort-web` is on your PATH (see Installation above):

```cmd
ort-web open
ort-web update
ort-web version
```

---

## Updating

When a new version is tagged on GitHub:

```bash
ort-web update
```

This will:
1. Check GitHub for the latest tag
2. `git fetch --tags` + `git checkout <tag>`
3. `pip install -e .` to install updated dependencies

---

## Usage

### Install ORT

On first launch, click **"Install ORT"** on the Dashboard. The installer downloads the latest ORT release from GitHub.

Default install locations:

| Platform | Path |
|----------|------|
| macOS (Apple Silicon) | `/opt/homebrew/bin` |
| macOS (Intel) | `/usr/local/bin` |
| Windows | `%LOCALAPPDATA%\Programs\ORT\bin` |
| Linux | `~/.local/bin` |

### Analyze a Project

1. Click **"Pick folder"** to select a project directory
2. Language is auto-detected (Python, Java, Go, Rust, Node.js, etc.)
3. Click **"Analyze"** to start

The analysis runs inline on the dashboard with realtime log streaming. Results appear when complete.

> **Note:** Folder picker on Linux requires `zenity` (GNOME) or `kdialog` (KDE) to be installed.

### Job History

Navigate to **"Job History"** in the sidebar to browse all past jobs with:
- Text search
- Status filter (success, failed, running, etc.)
- Language filter
- Time range (24h, 7d, 30d, 90d, custom)
- Pagination (10 per page)

Click **"View results"** on any job to see logs and generated files.

---

## Platform Support

| Feature | macOS | Windows | Linux |
|---------|-------|---------|-------|
| Web server | ✅ | ✅ | ✅ |
| Install ORT | ✅ | ✅ | ✅ |
| Folder picker | ✅ native | ✅ PowerShell | ✅ zenity/kdialog |
| CLI launcher | `ort-web` / `.sh` | `ort-web.bat` | `ort-web` / `.sh` |

---

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
  ort-web.sh           # Unix launcher (no venv activation needed)
  ort-web.bat          # Windows launcher (no venv activation needed)
  ARCHITECTURE.md      # Detailed app flow documentation
  pyproject.toml       # Package config + CLI entry point
```

See [ARCHITECTURE.md](ARCHITECTURE.md) for detailed application flow.

## License

MIT
