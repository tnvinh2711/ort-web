# ORT Web — Architecture & Application Flow

## Overview

ORT Web is a local web GUI for [OSS Review Toolkit (ORT)](https://github.com/oss-review-toolkit/ort) — a tool for scanning open-source dependencies for license compliance, vulnerability analysis, and dependency metadata collection.

**Tech Stack**: FastAPI + Jinja2 + HTMX + Server-Sent Events (SSE) + SQLite

**Architecture Style**: Feature-first modules under `app/features`.

---

## Feature-First Structure

```
app/
  features/
    routes.py          # Central route registration for all feature routers
    dashboard/       # Dashboard routes + analyze/install orchestration
    jobs/            # Job routes + queue + store + log stream
      event_contract.py  # Shared SSE event types and payload encoding
    results/         # Artifact browsing and file rendering
    setup/           # Setup routes + AI config persistence
    ort/             # ORT installer/executor/config/properties services
    analysis/        # Vulnerability summary + AI suggestion generation
    catalog/         # Commands/tools/plugins routes + ORT metadata registry
    shared/          # Shared helpers (language detection)
```

---

## Application Flow

### 1. Dashboard — Project Analysis

```
User opens /
  → KPI stats (total jobs, success, failed)
  → ORT status check (installed or not)
  → If not installed: Install ORT form
  → If installed: Project Analysis form

Pick Folder → /api/pick-directory (native OS dialog)
  → Auto-detect language → POST /api/detect-language
  → Show recommended package managers
  → Auto-generate config.yml + ort.properties

Click "Analyze" → POST /jobs/analyze-project (AJAX, no page reload)
  → Creates Job, enqueues to JobQueue
  → Returns {job_id}
  → JS fetches /jobs/{job_id}/panel → injects inline panel
  → SSE connects to /jobs/{job_id}/events
  → Realtime log streaming + status updates
  → On completion: refresh generated files via HTMX
```

### 2. Install ORT

```
Click "Install ORT" → POST /jobs/install-ort (AJAX)
  → Checks if already installed (DB + disk detection)
  → Creates ephemeral job (NOT saved to SQLite)
  → Downloads ORT from GitHub releases
  → Extracts + creates launcher binary
  → SSE streams status updates
  → On success: page reloads to show installed state
```

### 3. Job Detail Page

```
Navigate to /jobs/{job_id}
  → Full job info: name, status, language, timestamps, command
  → Log viewer (collapsed when done, open when running)
  → SSE for realtime log + status (if running)
  → Generated files table (HTMX auto-refresh every 5s when running)
  → /jobs/{job_id}/log-text — raw log endpoint for reload after completion
  → /jobs/{job_id}/files — HTMX partial for artifact file list
```

### 4. Job History

```
Navigate to /results/
  → Filters: text search, status dropdown, language dropdown, time range
  → Time range: All / 24h / 7d / 30d / 90d / Custom date picker
  → Pagination: 10 jobs/page
  → Card-based job items with status colors
  → "View results" link for success + failed jobs
```

---

## Route Map

| Method | Route | Purpose |
|--------|-------|---------|
| GET | `/` | Dashboard — KPI stats, ORT status, analysis form |
| POST | `/jobs/install-ort` | Install ORT (ephemeral, returns JSON) |
| POST | `/jobs/analyze-project` | Start analysis (returns JSON {job_id}) |
| GET | `/partials/jobs` | HTMX partial — paginated job list with filters |
| GET | `/api/pick-directory` | Native OS folder picker |
| POST | `/api/detect-language` | Detect project language |
| GET | `/jobs/{id}` | Job detail page (full page) |
| GET | `/jobs/{id}/panel` | HTMX partial — inline job panel for dashboard |
| GET | `/jobs/{id}/files` | HTMX partial — generated artifact files |
| GET | `/jobs/{id}/log-text` | Raw log text (plain text) |
| GET | `/jobs/{id}/events` | SSE stream — realtime log + status |
| GET | `/results/` | Job history page |
| GET | `/results/render` | Render artifact file in browser |
| GET | `/results/download` | Download artifact file |
| GET | `/setup/` | Environment setup — package manager detection |
| GET | `/tools/` | ORT core tools reference |
| GET | `/commands/` | ORT commands reference |
| GET | `/plugins/` | ORT plugins reference |

---

## Job Lifecycle

```
Created (pending)
  → JobQueue picks up
  → Status: running (SSE published)
  → ORT command executed (stdout streamed via SSE)
  → If analyze success: auto-run report for HTML generation
  → Status: success / failed (SSE published)
  → Stored in SQLite (persistent) or discarded (ephemeral)
```

**Ephemeral vs Persistent Jobs**:
- `ephemeral=True`: ORT install — streams logs but not saved to DB, not in job history
- `ephemeral=False`: Analysis jobs — saved to SQLite, visible in job history

---

## Services

| Service | Purpose |
|---------|---------|
| `features/jobs/queue.py` | AsyncIO queue with worker pool (default 2 parallel). Handles job lifecycle |
| `features/jobs/event_contract.py` | Canonical realtime event names / SSE payload format |
| `features/jobs/store.py` | SQLite persistence. CRUD + paged queries with filters |
| `features/jobs/log_stream.py` | Pub/sub for SSE events. Per-job subscriber queues |
| `features/ort/executor.py` | Executes ORT CLI. Validates commands, streams stdout |
| `features/ort/installer.py` | Downloads ORT from GitHub releases. Platform-specific extraction |
| `features/shared/language_detector.py` | Scans project files to detect language + recommend package managers |
| `features/ort/properties.py` | Generates `~/.ort/ort.properties` with enabled package managers |
| `features/ort/config.py` | Generates `config.yml` + per-project `.ort.yml` with path excludes |
| `features/analysis/ai_suggestion_report.py` | Builds AI remediation suggestions from ORT artifacts |
| `features/analysis/vuln_summary.py` | Aggregates vulnerability severities from advisor output |
| `features/routes.py` | Single place to include all feature routers into FastAPI app |
| `i18n` | JSON-based translations (Vietnamese + English) |

---

## Template Structure

```
templates/
  base.html                    # Sidebar layout + mobile header
  dashboard/
    index.html                 # KPI stats, ORT status, analysis form
    jobs_list.html             # Paginated job cards (HTMX partial)
  jobs/
    detail.html                # Full job detail page
    inline_panel.html          # Inline job panel for dashboard (HTMX partial)
    files_partial.html         # Artifact file list (HTMX partial)
  results/
    index.html                 # Job history with filters + pagination
  setup/
    index.html                 # Package manager detection + config
  tools/index.html             # ORT tools reference
  commands/index.html          # ORT commands reference
  plugins/index.html           # ORT plugins reference
  partials/
    job_panel.html             # Legacy job panel
```

---

## Design System

- **Style**: Glassmorphism SaaS (backdrop blur, glass cards)
- **Colors**: Blue primary (#1E40AF), Amber accent (#F59E0B)
- **Typography**: Inter (UI), JetBrains Mono (code)
- **Layout**: Fixed sidebar (240px) + responsive mobile hamburger
- **Components**: Status pills with dots, glass cards, progress bars, stat cards
- **i18n**: Vietnamese (default) + English, cookie-based persistence
