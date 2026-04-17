# ORT Web — System Diagrams

---

## 1. High Level Architecture

```mermaid
graph TB
    Browser["Browser"] -->|"HTTP / SSE"| API["FastAPI Server"]
    API --> JobQueue["Job Queue"]
    API --> JobStore["Job Store"]
    API --> LogHub["Log Stream Hub"]
    API --> VulnParser["Vuln Summary Parser"]
    JobQueue -->|"spawn"| ORT["ORT CLI"]
    JobStore --> DB[("SQLite")]
    ORT --> Artifacts["Artifacts"]
    VulnParser -->|"read advisor-result.yml"| Artifacts
    LogHub -->|"SSE"| Browser
    VulnParser -->|"counts by severity"| Browser
```

---

## 2. Functional Decomposition

```mermaid
graph LR
    ORT["ORT Web"]

    ORT --> A["Installation"]
    ORT --> B["Job Management"]
    ORT --> C["Project Analysis"]
    ORT --> D["Results"]
    ORT --> E["Configuration"]

    A --> A1["Install ORT + Java"]
    A --> A2["Verify Installation"]

    B --> B1["Queue & Execute Jobs"]
    B --> B2["Monitor / Cancel"]
    B --> B3["Persist History"]

    C --> C1["Detect Language"]
    C --> C2["Run ORT Analyze"]
    C --> C3["Stream Logs via SSE"]
    C --> C4["Auto-run Advise (OSV)"]
    C --> C5["Auto-run Report"]

    D --> D1["Browse Job History"]
    D --> D2["View Logs & Reports"]
    D --> D3["Download Artifacts"]
    D --> D4["Vulnerability Warning Banner"]

    E --> E1["Select Package Managers"]
    E --> E2["Generate config.yml"]
    E --> E3["Generate ort.properties"]
```

---

## 3. Use Case Diagram

```mermaid
flowchart LR
    Dev(["Developer"])
    CO(["Compliance Officer"])
    Ops(["DevOps Engineer"])

    subgraph System ["ORT Web"]
        UC1(["Scan Project Dependencies"])
        UC2(["Generate Compliance Report"])
        UC3(["Review Scan Results"])
        UC4(["Install ORT"])
        UC5(["Configure Scan Environment"])
        UC6(["View Vulnerability Warnings"])

        UC1 -->|"<<include>>"| UC4
        UC2 -->|"<<include>>"| UC1
        UC3 -->|"<<extend>>"| UC2
        UC6 -->|"<<include>>"| UC1
    end

    Dev --> UC1
    Dev --> UC3
    Dev --> UC6
    CO --> UC2
    CO --> UC3
    CO --> UC6
    Ops --> UC4
    Ops --> UC5
```

---

## 4. Data Flow

```mermaid
flowchart LR
    User(["User"])

    User -->|"pick folder"| LD["Language Detector"]
    LD -->|"detected language"| User

    User -->|"submit"| CG["Config Generator"]
    CG -->|"write config"| OrtCfg[("~/.ort/")]
    CG -->|"enqueue"| JQ["Job Queue"]

    JQ -->|"save"| DB[("SQLite")]
    JQ -->|"execute"| OE["ORT Executor"]
    OrtCfg --> OE
    OE -->|"SSE push"| User

    OE -->|"1 analyze"| AN["ORT Analyze"]
    AN -->|"write"| AR[("analyzer-result.yml")]

    AR -->|"2 advise"| ADV["ORT Advise\n(OSV)"]
    ADV -->|"write"| VR[("advisor-result.yml")]

    VR -->|"3 report"| RPT["ORT Report"]
    RPT -->|"write"| WA[("scan-report-web-app.html")]

    VR -->|"parse"| VS["Vuln Summary\nParser"]
    VS -->|"critical/high/medium/low"| User

    DB -->|"history"| User
    WA -->|"view / download"| User
```

---

## 5. Analyze Pipeline (Single Job)

```mermaid
sequenceDiagram
    participant U as User
    participant Q as Job Queue
    participant E as ORT Executor
    participant O as ORT CLI

    U->>Q: Submit analyze job
    Q->>E: Dequeue & run
    E->>O: ort analyze -i <project>
    O-->>E: analyzer-result.yml
    E-->>U: SSE log stream

    Note over E,O: Auto-chain step 1
    E->>O: ort advise --advisors OSV
    O-->>E: advisor-result.yml
    E-->>U: SSE log stream

    Note over E,O: Auto-chain step 2
    E->>O: ort report (WebApp + StaticHtml)
    O-->>E: scan-report-web-app.html
    E-->>U: SSE log stream

    Q-->>U: status = SUCCESS
    U->>E: GET /jobs/{id}/panel
    E-->>U: Vulnerability banner (critical/high/medium/low)
```
