// swift-tools-version:5.9
import PackageDescription

// Unlike PaymentKit/AnalyticsKit, this local package declares its own remote
// dependency. That dependency IS resolvable by ORT (via the local manifest)
// even though it never appears in the Xcode project's Package.resolved — which
// is what makes local packages checkable for CVEs at all.
let package = Package(
    name: "NetworkKit",
    platforms: [.macOS(.v12)],
    products: [
        .library(name: "NetworkKit", targets: ["NetworkKit"])
    ],
    dependencies: [
        // CVE-2022-24721 — Vapor FileMiddleware directory traversal
        .package(url: "https://github.com/vapor/vapor.git", exact: "4.53.0"),
    ],
    targets: [
        .target(
            name: "NetworkKit",
            dependencies: [.product(name: "Vapor", package: "vapor")]
        )
    ]
)
