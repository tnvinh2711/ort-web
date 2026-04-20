# ORT Web — Training Guide (English)

> **Version:** 0.3.0 | **Audience:** Development teams, Compliance officers, DevOps engineers

---

## Table of Contents

1. [What is ORT Web?](#1-what-is-ort-web)
2. [Prerequisites](#2-prerequisites)
3. [Installation & First Launch](#3-installation--first-launch)
4. [Dashboard Overview](#4-dashboard-overview)
5. [Installing ORT (One-time setup)](#5-installing-ort-one-time-setup)
6. [Analyzing a Project](#6-analyzing-a-project)
7. [Understanding Analysis Results](#7-understanding-analysis-results)
8. [Job History & Filtering](#8-job-history--filtering)
9. [Viewing & Downloading Reports](#9-viewing--downloading-reports)
10. [Switching Languages](#10-switching-languages)
11. [Updating ORT Web](#11-updating-ort-web)
12. [Common Issues & Troubleshooting](#12-common-issues--troubleshooting)
13. [FAQ](#13-faq)

---

## 1. What is ORT Web?

**ORT Web** is a local web-based graphical interface for the [OSS Review Toolkit (ORT)](https://github.com/oss-review-toolkit/ort) — an industry-standard open-source compliance and security scanning tool used by companies to manage open-source risk.

### What problems does it solve?

| Problem | ORT Web Solution |
|---------|-----------------|
| ORT is command-line only — hard to use | Browser-based GUI, no CLI knowledge needed |
| ORT setup is complex | One-click automated installation |
| No visibility into scan progress | Real-time log streaming in browser |
| Results are raw YAML files | Visual reports with vulnerability summaries |
| No audit trail | Persistent job history with search & filter |

### Who uses it?

- **Developers** — check open-source dependencies before shipping features
- **Compliance officers** — audit license usage across projects
- **DevOps engineers** — integrate into CI pipelines and run scans at scale

### What it scans

ORT Web can analyze projects written in:

| Language | Package Managers |
|----------|-----------------|
| Python | pip, Poetry |
| Java / Kotlin | Maven, Gradle |
| JavaScript / TypeScript | npm, Yarn, pnpm |
| Go | Go modules |
| Rust | Cargo |
| C# / .NET | NuGet |
| C / C++ | Conan |
| Ruby | Bundler |
| PHP | Composer |
| Swift | Swift PM |

---

## 2. Prerequisites

Before installing ORT Web, ensure the following are installed on your machine:

| Requirement | Version | How to check |
|-------------|---------|-------------|
| Python | 3.9 or later | `python --version` |
| Java | 21 or later | `java -version` |

**Linux only (for folder picker dialog):**
- GNOME desktop: `sudo apt install zenity`
- KDE desktop: `sudo apt install kdialog`

---

## 3. Installation & First Launch

### Step 1: Copy the ORT Web folder to your machine

Obtain the `ort-web` folder from your administrator (via USB, shared drive, or zip file) and copy it to a location on your machine, for example:

```
C:\Tools\ort-web          ← Windows
/Users/name/Tools/ort-web ← macOS / Linux
```

Then open Terminal / Command Prompt and navigate into that folder:

```bash
cd /path/to/ort-web
```

### Step 2: Create a virtual environment

```bash
python -m venv .venv
source .venv/bin/activate        # macOS / Linux
# OR
.venv\Scripts\activate           # Windows
```

### Step 3: Install ORT Web

```bash
pip install -e .
```

This installs the `ort-web` command globally in your environment.

### Step 4: (Optional) Create a global symlink

To use `ort-web` from any directory:

```bash
# macOS / Linux
sudo ln -sf $(which ort-web) /usr/local/bin/ort-web
```

### Step 5: Launch the application

```bash
ort-web
# OR
ort-web open          # same as above, opens browser automatically
ort-web open -p 3000  # use a custom port (default is 8000)
```

The browser will open automatically at `http://localhost:8000`.

---

## 4. Dashboard Overview

When you open ORT Web, you land on the **Dashboard** — the main control center.

```
┌─────────────────────────────────────────────────────────────┐
│  SIDEBAR                  │  MAIN CONTENT                   │
│  ─────────                │  ─────────────                  │
│  Dashboard            ←   │  [KPI Cards]                    │
│  Job History              │  Total Jobs | Success | Failed  │
│                           │                                  │
│                           │  [ORT Status]                   │
│                           │  ✅ ORT is installed / ⚠️ Not   │
│                           │                                  │
│                           │  [Install ORT] (if not ready)   │
│                           │                                  │
│                           │  [Analyze Project]              │
│                           │  - Pick folder                  │
│                           │  - Auto-detected language       │
│                           │  - [Run Analysis] button        │
└─────────────────────────────────────────────────────────────┘
```

### KPI Cards explained

| Card | What it shows |
|------|--------------|
| **Total Jobs** | All scans ever run |
| **Successful** | Jobs that completed without error |
| **Failed** | Jobs that encountered errors |
| **ORT Status** | Whether ORT binary is installed and ready |

---

## 5. Installing ORT (One-time setup)

ORT Web automates the entire ORT installation process. You only need to do this once.

### Steps

1. On the Dashboard, look for the **"Install ORT"** section
2. Optionally, click **"Pick folder"** to choose where ORT will be installed
   - Default: inside the ORT Web runtime directory
3. Click the **"Install ORT"** button
4. Watch the real-time installation log appear below

### What happens during installation

```
[1] Fetch latest ORT release from GitHub
[2] Detect platform (macOS / Windows / Linux)
[3] Verify Java 21+ is available
[4] Download ORT binary archive
[5] Extract to selected directory
[6] Create launcher script (ort-web.sh or ort-web.bat)
[7] Mark installation as complete
```

### After installation

- The ORT Status card on the Dashboard shows **"ORT is installed ✅"**
- You are now ready to analyze projects

> **Note:** If Java 21+ is not found, the installation will fail with an error. Install Java first, then retry.

---

## 6. Analyzing a Project

This is the core workflow — running a dependency scan on a software project.

### Step-by-step

#### Step 1: Select the project folder

1. Click the **"Pick folder"** button on the Dashboard
2. A native file browser dialog opens
3. Navigate to and select your project's root directory (where `pom.xml`, `package.json`, `requirements.txt`, etc. are located)
4. Click **"Open"** / **"Select"**

#### Step 2: Review auto-detected language

After selecting the folder, ORT Web automatically scans the project files and detects the programming language:

| What you'll see | Meaning |
|-----------------|---------|
| `Python` | Found `.py` files, `requirements.txt`, `pyproject.toml` |
| `Node.js` | Found `package.json`, `node_modules` |
| `Java` | Found `pom.xml` or `build.gradle` |
| etc. | ... |

The tool also shows the **recommended package managers** for that language.

> **If detection is wrong:** Use the language dropdown to manually select the correct language.

#### Step 3: Run the analysis

1. Verify the project path and language are correct
2. Click **"Analyze"** button
3. An inline **Job Panel** appears on the dashboard showing:
   - Job name and ID
   - Current status (Pending → Running → Success/Failed)
   - Real-time log output

#### Step 4: Monitor progress

The analysis runs 3 sequential steps — watch them in the live log:

```
Step 1: ANALYZE
  ort analyze -i /path/to/project -o /path/to/output
  → Scans all dependencies
  → Produces: analyzer-result.yml

Step 2: ADVISE
  ort advise --advisors OSV -i analyzer-result.yml -o /path/to/output
  → Checks all dependencies against the OSV vulnerability database
  → Produces: advisor-result.yml

Step 3: REPORT
  ort report --report-formats WebApp,StaticHtml -i advisor-result.yml -o /path/to/output
  → Generates human-readable compliance reports
  → Produces: scan-report-web-app.html, scan-report.html
```

#### Step 5: View results

When the job completes:
- Status changes to **"Success"** (green) or **"Failed"** (red)
- A **Vulnerability Summary** is displayed if any issues were found
- Generated files are listed with download/view buttons
- Click **"View Details"** to open the full Job Detail page

---

## 7. Understanding Analysis Results

### Vulnerability Summary

After analysis, ORT Web parses the OSV advisor results and displays a summary:

```
┌────────────────────────────────────────┐
│  Vulnerability Summary                 │
│  ─────────────────────────────────     │
│  🔴 Critical:  3                       │
│  🟠 High:      12                      │
│  🟡 Medium:    8                       │
│  🟢 Low:       5                       │
└────────────────────────────────────────┘
```

**Severity levels:**
- **Critical** — Exploitable remotely, no authentication needed. Fix immediately.
- **High** — Significant risk. Fix before next release.
- **Medium** — Moderate risk. Plan to fix in upcoming sprint.
- **Low** — Minimal impact. Fix when convenient.

### Generated files

| File | Contents |
|------|----------|
| `analyzer-result.yml` | Full dependency tree, license data, package metadata |
| `advisor-result.yml` | Vulnerabilities found by OSV, CVE details, affected versions |
| `scan-report-web-app.html` | Interactive web application report (best for browsing) |
| `scan-report.html` | Static HTML report (good for sharing/archiving) |

### Reading the HTML report

1. Click the HTML report file in the Job Detail page
2. The report opens in a new browser tab
3. Sections of the report:

| Section | What to look at |
|---------|----------------|
| **Summary** | High-level statistics, counts by severity |
| **Dependencies** | Full dependency tree with licenses |
| **Vulnerabilities** | CVE IDs, affected packages, CVSS scores, fix versions |
| **Licenses** | All licenses used, policy violations (if configured) |

---

## 8. Job History & Filtering

The **Job History** page gives you a complete audit trail of all past scans.

### Accessing

Click **"Job History"** in the left sidebar.

### Understanding the job list

Each job card shows:
- **Name** — the project folder name used as the job name
- **Language** — detected language
- **Status** — color-coded pill (Success / Failed / Running / Pending / Cancelled)
- **Created at** — when the job was submitted
- **Duration** — how long the scan took

### Filtering jobs

| Filter | How to use |
|--------|-----------|
| **Search by name** | Type in the text box — filters instantly |
| **Status** | Dropdown: All / Success / Failed / Running / Pending / Cancelled |
| **Language** | Dropdown: All / Python / Java / Node.js / Go / etc. |
| **Time range** | Quick buttons: 24h / 7d / 30d / 90d |
| **Custom date** | Click "Custom" and pick start/end dates |

### Pagination

- 10 jobs per page
- Use numbered page buttons to navigate
- Filters apply across all pages

### View a past job

Click the **"View Results"** button on any job card to go to the Job Detail page.

---

## 9. Viewing & Downloading Reports

### From Job History

1. Find the job in Job History
2. Click **"View Results"**

### From Job Detail page

The Job Detail page shows:

1. **Job Information** — name, status, language, start/end time, full ORT command used
2. **Execution Log** — complete log of the ORT run (collapsible)
3. **Generated Files** — table of all output files with:
   - File name
   - File size
   - Type (YAML, HTML, etc.)
   - View / Download buttons
4. **Vulnerability Summary** — severity counts

### Viewing HTML reports

- Click the **eye icon** or file name for HTML files
- The report opens in a new browser tab
- Navigate the interactive report sections

### Downloading files

- Click the **download icon** next to any file
- Files download to your browser's default download folder
- You can download: `analyzer-result.yml`, `advisor-result.yml`, HTML reports

### Copying the ORT command

- On the Job Detail page, find the **"Command"** section
- Click **"Copy"** to copy the exact ORT command to clipboard
- Useful for reproducing the scan manually or in CI

---

## 10. Switching Languages

ORT Web supports **Vietnamese** (default) and **English**.

### How to switch

1. Look for the language selector (top-right area or in the header)
2. Click **"English"** or **"Tiếng Việt"**
3. The UI updates immediately — all labels, buttons, and messages switch language
4. Your preference is saved automatically (cookie-based) and persists across sessions

---

## 11. Updating ORT Web

### Check current version

```bash
ort-web version
# OR
ort-web -V
```

### Update to a new version

To update ORT Web, obtain the new version folder from your administrator. Then:

1. **Stop** the running ORT Web (close the Terminal window)
2. **Copy** the new `ort-web` folder to your machine (replace the old one or place side-by-side)
3. **Navigate** into the new folder and re-activate the virtual environment:

```bash
cd /path/to/new-ort-web
source .venv/bin/activate    # macOS / Linux
.venv\Scripts\activate       # Windows
pip install -e .
```

4. **Launch** again: `ort-web open`

> **Note:** Job history data lives in the `runtime/` folder. To keep your history, copy the `runtime/` folder from the old version into the new one.

### Updating ORT itself

To update the ORT binary (not ORT Web), re-run the **"Install ORT"** process from the Dashboard — it always fetches the latest ORT release.

---

## 12. Common Issues & Troubleshooting

### "ORT not found" or "ORT is not installed"

**Cause:** ORT binary hasn't been installed yet, or was installed in a directory that's not on PATH.

**Fix:**
1. Go to Dashboard
2. Click "Install ORT" and follow the installation steps
3. If already installed manually, ensure the ORT binary directory is in your system PATH

---

### "Java not found" during ORT installation

**Cause:** Java 21+ is required by ORT but not installed or not on PATH.

**Fix:**
1. Install Java 21+ (e.g., [Eclipse Temurin](https://adoptium.net/))
2. Verify: `java -version` should show `21.x.x` or higher
3. Retry ORT installation

---

### Analysis job fails immediately

**Cause:** Could be missing package manager, network issues, or ORT config problems.

**Fix:**
1. Go to Job Detail page and read the full log
2. Look for the specific error message (usually at the bottom of the log)
3. Common causes:
   - `pip not found` → install pip or activate the correct Python environment
   - `mvn not found` → install Maven
   - Network timeout → check internet connection (OSV requires internet access)

---

### Folder picker doesn't open (Linux)

**Cause:** `zenity` or `kdialog` is not installed.

**Fix:**
```bash
sudo apt install zenity      # GNOME / Ubuntu
sudo apt install kdialog     # KDE
```

---

### Port 8000 is already in use

**Fix:**
```bash
ort-web open -p 3000    # use any available port
```

---

### Language detection is wrong

**Fix:** Use the language dropdown on the Dashboard to manually select the correct language before clicking "Analyze".

---

## 13. FAQ

**Q: How long does analysis take?**
A: Depends on project size and number of dependencies. Typical ranges:
- Small project (< 50 dependencies): 2–5 minutes
- Medium project (50–200 dependencies): 5–15 minutes
- Large project (200+ dependencies): 15–60 minutes

**Q: Can I run multiple analyses at the same time?**
A: Yes. ORT Web supports up to **2 parallel jobs** by default. Additional jobs are queued and run when a slot becomes available.

**Q: Where are the generated reports stored?**
A: In the `runtime/artifacts/` directory inside the ORT Web installation folder. You can also download them directly from the web interface.

**Q: What does "Failed" status mean?**
A: The ORT process exited with an error. Go to the Job Detail page and read the log to find the specific error. Common causes: missing package manager, dependency resolution failure, or network timeout.

**Q: Can I re-run a failed job?**
A: Currently, you need to submit a new analysis from the Dashboard. The project path from a failed job's detail page can be copied for convenience.

**Q: How do I know which licenses are problematic?**
A: The HTML report's **"Licenses"** section lists all licenses. Licenses flagged as violations depend on your ORT policy configuration (`~/.ort/config.yml`). Contact your compliance team for your organization's license policy.

---

*Last updated: April 2026 | ORT Web v0.3.0*
