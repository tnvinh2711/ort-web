// swift-tools-version:5.6
import PackageDescription

let package = Package(
    name: "SwiftVulnSample",
    platforms: [.macOS(.v12)],
    dependencies: [
        // CVE-2021-32762 — SwiftNIO HTTP request smuggling via malformed Transfer-Encoding header
        .package(url: "https://github.com/apple/swift-nio.git", exact: "2.28.0"),
        // GHSA-25hh-hxj3-rq32 — swift-nio-http2 CONTINUATION frame flood (unbounded memory growth / DoS)
        .package(url: "https://github.com/apple/swift-nio-http2.git", exact: "1.17.0"),
    ],
    targets: [
        .executableTarget(
            name: "SwiftVulnSample",
            dependencies: [
                .product(name: "NIO", package: "swift-nio"),
                .product(name: "NIOHTTP2", package: "swift-nio-http2"),
            ]
        )
    ]
)
