// Swift Package Manager vulnerable dependencies sample
// CVEs: swift-nio 2.28.0, swift-nio-http2 1.19.0

import NIO
import NIOHTTP2

// CVE-2021-32762: SwiftNIO HTTP request smuggling via malformed Transfer-Encoding header
func makeEventLoopGroup() -> MultiThreadedEventLoopGroup {
    MultiThreadedEventLoopGroup(numberOfThreads: 1)
}

// GHSA-25hh-hxj3-rq32: swift-nio-http2 CONTINUATION frame flood (unbounded memory growth)
func configureHTTP2(channel: Channel) {
    _ = channel.pipeline.addHandler(NIOHTTP2Handler(mode: .server))
}

let group = makeEventLoopGroup()
print("Swift vuln sample")
