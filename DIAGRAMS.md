# ORT Web — System Diagrams

---

## 1. High Level Architecture

```mermaid
graph TB
    Browser["Browser"] -->|"HTTP / SSE"| API["FastAPI Server"]
    API --> JobQueue["Job Queue"]
    API --> JobStore["Job Store"]
    API --> LogHub["Log Stream Hub"]
    JobQueue -->|"spawn"| ORT["ORT CLI"]
    JobStore --> DB[("SQLite")]
    ORT --> Artifacts["Artifacts"]
    LogHub -->|"SSE"| Browser
    ORT -->|"download"| GitHub["GitHub API"]
```

---

## 2. Functional Decomposition

```mermaid
graph TB
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
    C --> C2["Run ORT Command"]
    C --> C3["Stream Logs via SSE"]
    C --> C4["Auto-run Report"]

    D --> D1["Browse Job History"]
    D --> D2["View Logs & Reports"]
    D --> D3["Download Artifacts"]

    E --> E1["Select Package Managers"]
    E --> E2["Generate config.yml"]
    E --> E3["Generate ort.properties"]
```

---

## 3. Use Case Diagram

> Mô tả mục tiêu của từng actor khi tương tác với hệ thống. `<<include>>` = use case con bắt buộc phải chạy; `<<extend>>` = use case mở rộng tùy chọn.

```mermaid
flowchart LR
    Dev(["Developer"])
    CO(["Compliance Officer"])
    Ops(["DevOps Engineer"])

    subgraph System ["ORT Web System"]
        UC1(["Scan Project Dependencies"])
        UC2(["Generate Compliance Report"])
        UC3(["Review Scan Results"])
        UC4(["Install ORT Tool"])
        UC5(["Configure Scan Environment"])
        UC6(["Monitor Scan Progress"])
        UC7(["Download SBOM / Artifacts"])

        UC1 -->|"<<include>>"| UC4
        UC1 -->|"<<include>>"| UC6
        UC2 -->|"<<include>>"| UC1
        UC3 -->|"<<extend>>"| UC7
    end

    Dev --> UC1
    Dev --> UC3

    CO --> UC2
    CO --> UC3

    Ops --> UC4
    Ops --> UC5
```

---

## 4. Data Flow

```mermaid
flowchart LR
    User(["User"])

    User -->|"pick folder"| LD["Language Detector"]
    LD -->|"scan files"| LD
    LD -->|"detected language"| User

    User -->|"submit"| CG["Config Generator"]
    CG -->|"write config"| OrtCfg[("~/.ort/")]
    CG -->|"enqueue"| JQ["Job Queue"]

    JQ -->|"save"| DB[("SQLite")]
    JQ -->|"execute"| OE["ORT Executor"]
    OrtCfg --> OE
    OE -->|"spawn"| ORT["ORT CLI"]
    ORT -->|"stdout"| OE
    OE -->|"SSE push"| User
    ORT -->|"write"| ART["Artifacts"]

    DB -->|"history"| User
    ART -->|"view / download"| User
```
