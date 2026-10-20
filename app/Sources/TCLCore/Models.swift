import Foundation

public struct Channels: Codable, Equatable, Sendable {
    public var remote: Bool
    public var adb: Bool

    public init(remote: Bool, adb: Bool) {
        self.remote = remote
        self.adb = adb
    }
}

public struct Health: Codable, Equatable, Sendable {
    public var ok: Bool
    public var tvHost: String?
    public var tvMac: String?
    public var channels: Channels
    public var adbAuth: String?

    public init(ok: Bool, tvHost: String?, tvMac: String?, channels: Channels, adbAuth: String?) {
        self.ok = ok
        self.tvHost = tvHost
        self.tvMac = tvMac
        self.channels = channels
        self.adbAuth = adbAuth
    }
}

public struct Volume: Codable, Equatable, Sendable {
    public var level: Int
    public var max: Int
    public var muted: Bool

    public init(level: Int, max: Int, muted: Bool) {
        self.level = level
        self.max = max
        self.muted = muted
    }
}

public struct TVState: Codable, Equatable, Sendable {
    public var power: String?
    public var app: String?
    public var volume: Volume?
    public var channels: Channels
    public var adbAuth: String?

    public init(power: String?, app: String?, volume: Volume?, channels: Channels, adbAuth: String?) {
        self.power = power
        self.app = app
        self.volume = volume
        self.channels = channels
        self.adbAuth = adbAuth
    }
}

public enum SidecarError: Error, Equatable, Sendable {
    case api(code: String, message: String, status: Int)
    case notRunning
    case timeout
    case invalidResponse
}

public struct InputPort: Codable, Equatable, Sendable, Identifiable {
    public var port: Int
    public var id: String
    public var label: String
    public var connected: Bool
    public var active: Bool

    public init(port: Int, id: String, label: String, connected: Bool, active: Bool) {
        self.port = port
        self.id = id
        self.label = label
        self.connected = connected
        self.active = active
    }
}

public struct PictureModeOption: Codable, Equatable, Sendable, Identifiable {
    public var id: String
    public var label: String

    public init(id: String, label: String) {
        self.id = id
        self.label = label
    }
}

public struct PictureState: Codable, Equatable, Sendable {
    public var mode: String
    public var modeId: String
    public var modes: [PictureModeOption]
    public var backlight: Int
    public var cachedAt: String

    public init(mode: String, modeId: String, modes: [PictureModeOption], backlight: Int, cachedAt: String) {
        self.mode = mode
        self.modeId = modeId
        self.modes = modes
        self.backlight = backlight
        self.cachedAt = cachedAt
    }
}
