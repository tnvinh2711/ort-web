// swift-tools-version:5.9
import PackageDescription

let package = Package(
    name: "AnalyticsKit",
    platforms: [.iOS(.v15)],
    products: [
        .library(name: "AnalyticsKit", targets: ["AnalyticsKit"])
    ],
    targets: [
        .target(name: "AnalyticsKit")
    ]
)
