import Foundation
import Observation

public struct InputName: Codable, Equatable, Sendable {
    public var name: String
    public var symbol: String
    public var hidden: Bool

    public init(name: String, symbol: String, hidden: Bool) {
        self.name = name
        self.symbol = symbol
        self.hidden = hidden
    }
}

@MainActor @Observable
public final class InputNamesStore {
    public static let symbols: [String] = [
        "gamecontroller.fill", "appletv.fill", "laptopcomputer", "tv.fill",
        "hifispeaker.fill", "play.rectangle.fill", "cable.connector",
    ]

    private static let key = "inputNames"

    private var stored: [String: InputName]
    @ObservationIgnored private let defaults: UserDefaults

    public init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
        if let data = defaults.data(forKey: Self.key),
           let decoded = try? JSONDecoder().decode([String: InputName].self, from: data) {
            stored = decoded
        } else {
            stored = [:]
        }
    }

    public func name(for port: Int) -> InputName {
        if let v = stored[String(port)] { return v }
        return InputName(name: "HDMI \(port)", symbol: "cable.connector", hidden: false)
    }

    public func set(_ value: InputName, for port: Int) {
        stored[String(port)] = value
        if let data = try? JSONEncoder().encode(stored) {
            defaults.set(data, forKey: Self.key)
        }
    }
}
