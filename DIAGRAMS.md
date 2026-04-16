# ORT Web — System Diagrams

Tài liệu này tổng hợp 4 loại diagram mô tả kiến trúc và luồng hoạt động của hệ thống ORT Web.

---

## 1. High Level Architecture Diagram

> Mô tả tổng quan kiến trúc hệ thống: Browser → FastAPI Server → Data Layer → External Systems.

```mermaid
graph TB
    subgraph Browser ["Browser (Client)"]
        UI["Web UI - Jinja2 + HTMX"]
        SSEClient["SSE Client - Real-time Logs"]
    end
    subgraph Server ["FastAPI Application Server"]
        subgraph Routers ["Route Handlers"]
            Dashboard["Dashboard"]
            Jobs["Jobs Router"]
            Results["Results"]
            Setup["Setup"]
            Reference["Tools / Commands / Plugins"]
        end
        subgraph Services ["Service Layer"]
            JobQueue["Job Queue - Async Workers"]
            JobStore["Job Store - SQLite CRUD"]
            OrtExec["ORT Executor - Subprocess"]
            OrtInst["ORT Installer"]
            LangDet["Language Detector"]
            LogHub["Log Stream Hub - Pub/Sub"]
            OrtConf["Config Generator"]
        end
    end
    subgraph Data ["Data Layer"]
        SQLite[("SQLite DB - Jobs")]
        Logs["Log Files"]
        Artifacts["Artifacts - HTML / SBOM / YAML"]
        OrtBin["ORT Binary + Launchers"]
        OrtConfig["~/.ort/ Config Files"]
    end
    subgraph Ext ["External Systems"]
        GitHub["GitHub API - ORT Releases"]
        ORT["ORT CLI - Subprocess"]
        Java["Java 21+ Runtime"]
        OSPicker["OS Folder Picker"]
    end

    UI -->|"HTTP requests"| Dashboard & Jobs & Results & Setup & Reference
    SSEClient -->|"EventSource GET /events"| Jobs
    Dashboard --> JobQueue & LangDet & OrtInst
    Jobs --> JobQueue & JobStore & LogHub
    Results --> JobStore
    Setup --> OrtConf & LangDet
    LangDet --> OSPicker
    JobQueue --> JobStore & OrtExec
    OrtExec -->|"spawn"| ORT
    OrtExec --> Logs & LogHub
    OrtInst --> GitHub & Java & OrtBin
    JobStore --> SQLite
    ORT --> Artifacts
    OrtConfig -->|"config.yml + ort.properties"| ORT
    LogHub -->|"SSE events"| SSEClient
```

---

## 2. Functional Decomposition Diagram

> Phân rã hệ thống thành 6 nhóm chức năng chính và các sub-function tương ứng.

```mermaid
graph TB
    ORT["ORT Web System"]

    ORT --> IM["Installation Management"]
    ORT --> JM["Job Management"]
    ORT --> PA["Project Analysis"]
    ORT --> RM["Results Management"]
    ORT --> CM["Configuration Management"]
    ORT --> REF["Reference and Documentation"]

    IM --> IM1["Detect Java 21+"]
    IM --> IM2["Download ORT from GitHub"]
    IM --> IM3["Create Platform Launchers"]
    IM --> IM4["Verify ORT Installation"]

    JM --> JM1["Queue Jobs - Async Workers"]
    JM --> JM2["Execute Jobs - Subprocess"]
    JM --> JM3["Monitor Job Status"]
    JM --> JM4["Cancel Running Jobs"]
    JM --> JM5["Persist Job History - SQLite"]

    PA --> PA1["Pick Project Directory - OS Dialog"]
    PA --> PA2["Auto-detect Project Language"]
    PA --> PA3["Select ORT Command"]
    PA --> PA4["Stream Logs Real-time - SSE"]
    PA --> PA5["Auto-run Follow-up Reports"]

    RM --> RM1["Browse Job History"]
    RM --> RM2["Filter and Search Jobs"]
    RM --> RM3["View Raw Logs"]
    RM --> RM4["Render HTML Reports"]
    RM --> RM5["Download Artifacts"]

    CM --> CM1["Detect Package Managers - 18 Ecosystems"]
    CM --> CM2["Configure Enabled Managers"]
    CM --> CM3["Generate ort.properties"]
    CM --> CM4["Generate config.yml"]
    CM --> CM5["Set Repository Path Excludes"]

    REF --> REF1["ORT Core Tools Reference"]
    REF --> REF2["ORT Commands Reference"]
    REF --> REF3["ORT Plugins Explorer"]
```

---

## 3. Use Case Diagram

> Mô tả các actor và use case trong hệ thống: Developer, Compliance Officer, DevOps Engineer.

```mermaid
flowchart LR
    DEV(["Developer"])
    CO(["Compliance Officer"])
    DEVOPS(["DevOps Engineer"])

    subgraph ORT ["ORT Web Use Cases"]
        UC1["Install ORT"]
        UC2["Pick Project Directory"]
        UC3["Auto-detect Project Language"]
        UC4["Run ORT Analyze"]
        UC5["Monitor Real-time Logs"]
        UC6["View Job Results"]
        UC7["Download Artifacts"]
        UC8["Browse and Filter Job History"]
        UC9["Run Full Compliance Pipeline"]
        UC10["Configure Package Managers"]
        UC11["Generate ort.properties"]
        UC12["Generate config.yml"]
        UC13["Set Path Excludes"]
        UC14["Explore ORT Tools and Plugins"]
    end

    DEV --> UC1 & UC2 & UC3 & UC4 & UC5 & UC6 & UC7 & UC8 & UC14
    CO --> UC1 & UC9 & UC5 & UC6 & UC7 & UC8
    DEVOPS --> UC1 & UC10 & UC11 & UC12 & UC13 & UC14
```

---

## 4. Data Flow Diagram

> Luồng dữ liệu từ đầu vào (user chọn folder) qua xử lý (Language Detection → Job Queue → ORT Executor) đến đầu ra (Artifacts, SSE logs, Job History).

```mermaid
flowchart LR
    User(["User"])

    User -->|"1. Select project folder"| OSPicker["OS Folder Picker"]
    OSPicker -->|"2. Return folder path"| LangDet["Language Detector"]
    LangDet -->|"3. Scan file patterns"| PFiles["Project Files"]
    PFiles -->|"4. Matched patterns"| LangDet
    LangDet -->|"5. Language + package managers"| User

    User -->|"6. Choose ORT command and submit"| ConfGen["Config Generator"]
    ConfGen -->|"7. Write config.yml + ort.properties"| OrtCfg[("ORT Config Files ~/.ort/")]
    ConfGen -->|"8. Enqueue job"| JobQueue["Job Queue - Async Workers"]

    JobQueue -->|"9. Persist job record"| SQLite[("SQLite DB")]
    JobQueue -->|"10. Dispatch to worker"| OrtExec["ORT Executor"]

    OrtCfg -->|"11. Read config at runtime"| ORT["ORT CLI"]
    OrtExec -->|"12. Spawn subprocess"| ORT
    ORT -->|"13. stdout log lines"| OrtExec
    OrtExec -->|"14. Append lines"| LogFiles["Log Files"]
    OrtExec -->|"15. Publish line events"| LogHub["Log Stream Hub"]
    LogHub -->|"16. SSE push"| User

    ORT -->|"17. Write results"| Artifacts["Artifacts - scan-report.html / analyzer-result.yml / SBOM"]
    JobQueue -->|"18. Auto-run ort report"| OrtExec

    SQLite -->|"19. Job list + details"| User
    Artifacts -->|"20. Render or Download"| User
    LogFiles -->|"21. View full log"| User
```
