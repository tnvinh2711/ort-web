// Xcode app target. Dependencies are declared in the .xcodeproj (as Swift
// Package references), not in a root Package.swift — this file only consumes
// them.

import AnalyticsKit
import Lottie
import NIO
import NIOHTTP2
import PaymentKit
import UIKit

@main
class AppDelegate: UIResponder, UIApplicationDelegate {
    let payments = PaymentKit()
    let analytics = AnalyticsKit()

    // CVE-2021-32762 / CVE-2026-28980: swift-nio 2.28.0
    let group = MultiThreadedEventLoopGroup(numberOfThreads: 1)

    // GHSA-25hh-hxj3-rq32 / CVE-2022-24666: swift-nio-http2 1.17.0
    func configureHTTP2(channel: Channel) {
        _ = channel.pipeline.addHandler(NIOHTTP2Handler(mode: .client))
    }

    func application(
        _ application: UIApplication,
        didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]?
    ) -> Bool {
        analytics.track("app_launched")
        _ = payments.makeTransfer(amount: 10, to: "0123456789")
        _ = LottieAnimationView(name: "splash")
        return true
    }
}
