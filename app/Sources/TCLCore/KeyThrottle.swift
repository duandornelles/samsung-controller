import Foundation

public struct KeyThrottle: Sendable {
    private let interval: Duration
    private var last: [String: ContinuousClock.Instant] = [:]

    public init(interval: Duration = .milliseconds(150)) {
        self.interval = interval
    }

    public mutating func shouldSend(_ key: String, at now: ContinuousClock.Instant) -> Bool {
        if let prev = last[key], now - prev < interval { return false }
        last[key] = now
        return true
    }
}
