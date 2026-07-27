# swift-xcode-vuln

Xcode app project with Swift Package dependencies — **no root `Package.swift`**.
This is the layout most real iOS apps use, and it differs from `swift-vuln/`
(a plain SwiftPM package) in ways that matter for scanning:

```
WonSample.xcodeproj/
  project.xcworkspace/xcshareddata/swiftpm/Package.resolved   <- Xcode-level remote pins
LocalPackages/
  PaymentKit/Package.swift          <- local package -> local AnalyticsKit
  AnalyticsKit/Package.swift        <- local package, no dependencies
  NetworkKit/Package.swift          <- local package WITH its own remote dependency
  NetworkKit/Package.resolved       <- ...and its own resolved pins
WonSample/AppDelegate.swift
```

## What each scanner sees

| What | Where it is declared | ORT | Trivy |
|---|---|---|---|
| Xcode-level remote deps | `.xcodeproj/…/swiftpm/Package.resolved` | ✅ | ✅ |
| Local package's deps, `Package.resolved` present | local `Package.resolved` | ✅ | ✅ |
| Local file-system package dependency | `.package(path: "../AnalyticsKit")` | manifest found; see limitation below | source-only |
| Local package's remote deps, only a manifest | local `Package.swift` | ✅ (runs `swift`) | ❌ |
| The local package's own source | — | listed as a project, no CVE data | ❌ |

Two things drive this:

- **Trivy vulnerability detection reads `Package.resolved`.** Its separate full
  license pass scans source files already present in the project. OSS Guard
  resolves local `Package.swift` manifests first, creating `.build/checkouts`;
  it does not clone Xcode-level pins, so those pins can have vulnerabilities but
  no Trivy license result when no source checkout exists.
- **ORT reads both.** It treats `Package.resolved` as a definition file in its
  own right (no `swift` invocation, so it is immune to `swift-tools-version`
  mismatches), and for a bare `Package.swift` it shells out to
  `swift package show-dependencies` — which does require a matching toolchain.
  ORT ScanCode runs automatically for Swift and its `scan-result.yml` feeds OSV
  advice so license and vulnerability findings survive in the final report.

A local package's *own* code is first-party and appears in no vulnerability
database; OSV logs `does not provide any metadata to identify vulnerabilities`
for it. Only its dependencies can be checked. Note also that ORT's `scan` step
is ScanCode — **license** detection, not CVE detection. Vulnerabilities come
from the `advise` step (OSV).

Current ORT SwiftPM versions try to convert the absolute URL returned by
`swift package show-dependencies` for `.package(path: ...)` into a PackageURL
and report `MalformedPackageURLException`. OSS Guard warns about this during
precheck. The local manifest is still discovered as a first-party project, and
its source remains covered by ScanCode and Trivy. Versioned remote dependencies
should have a `Package.resolved`, which Trivy can scan even when this ORT issue
is present.

## Known vulnerabilities

Pinned deliberately at vulnerable versions:

- `swift-nio` 2.28.0 — CVE-2026-28980, CVE-2026-43671
- `swift-nio-http2` 1.17.0 — CVE-2022-0618, CVE-2022-24666/24667/24668
- `vapor` 4.53.0 (via `NetworkKit`) — CVE-2022-31005, CVE-2022-31019

`lottie-ios` 4.5.0 and `swift-argument-parser` 1.8.2 are current and included
only so the dependency graph resembles a real app. Vapor is server-side rather
than iOS, but the Swift ecosystem in OSV is sparse — `swift-nio*` and `vapor`
are effectively the only families with advisories, while common iOS libraries
(Alamofire, SDWebImage, KeychainAccess) currently have none.
