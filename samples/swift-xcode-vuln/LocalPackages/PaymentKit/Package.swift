// swift-tools-version:5.9
import PackageDescription

// Local (file-system) package, referenced by the Xcode project rather than by
// a root Package.swift. Local references carry no version/revision, so they
// never appear in Package.resolved — only their own manifest identifies them.
let package = Package(
    name: "PaymentKit",
    platforms: [.iOS(.v15)],
    products: [
        .library(name: "PaymentKit", targets: ["PaymentKit"])
    ],
    dependencies: [
        .package(path: "../AnalyticsKit")
    ],
    targets: [
        .target(
            name: "PaymentKit",
            dependencies: ["AnalyticsKit"]
        )
    ]
)
