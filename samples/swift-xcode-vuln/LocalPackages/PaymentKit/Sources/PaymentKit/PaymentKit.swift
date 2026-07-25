public struct PaymentKit {
    public init() {}

    public func makeTransfer(amount: Decimal, to account: String) -> String {
        "transfer \(amount) -> \(account)"
    }
}
