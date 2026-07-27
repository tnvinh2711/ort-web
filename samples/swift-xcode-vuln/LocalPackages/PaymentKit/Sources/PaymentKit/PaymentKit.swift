import AnalyticsKit
import Foundation

public struct PaymentKit {
    public init() {}

    public func makeTransfer(amount: Decimal, to account: String) -> String {
        AnalyticsKit().track("transfer")
        return "transfer \(amount) -> \(account)"
    }
}
