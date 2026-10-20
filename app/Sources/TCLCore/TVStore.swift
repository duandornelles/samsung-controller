import Foundation
import Observation

public enum MenuPhase: Equatable, Sendable {
    case startingSidecar, sidecarFailed(String), notPaired, standby, on, unknown

    public static func derive(sidecar: SidecarStatus, health: Health?, state: TVState?) -> MenuPhase {
        switch sidecar {
        case .starting: return .startingSidecar
        case .failed(let message): return .sidecarFailed(message)
        case .running: break
        }
        if let health, health.tvMac == nil { return .notPaired }
        switch state?.power {
        case "standby": return .standby
        case "on": return .on
        default: return .unknown
        }
    }
}

@MainActor @Observable
public final class TVStore {
    public private(set) var health: Health?
    public private(set) var state: TVState?
    public private(set) var transientError: String?
    public private(set) var lastErrorCode: String?
    public private(set) var pairingMessage: String?
    public private(set) var inputs: [InputPort] = []
    public private(set) var picture: PictureState?
    public private(set) var pictureLoading = false

    @ObservationIgnored private let api: SidecarAPI
    @ObservationIgnored private let sidecar: SidecarStatusSource
    @ObservationIgnored private let pollInterval: Duration
    @ObservationIgnored private let errorDuration: Duration
    @ObservationIgnored private let sleep: (Duration) async throws -> Void
    @ObservationIgnored private var pollTask: Task<Void, Never>?
    @ObservationIgnored private var clearTask: Task<Void, Never>?

    public init(
        api: SidecarAPI,
        sidecar: SidecarStatusSource,
        pollInterval: Duration = .seconds(3),
        errorDuration: Duration = .seconds(3),
        sleep: @escaping (Duration) async throws -> Void = { try await Task.sleep(for: $0) }
    ) {
        self.api = api
        self.sidecar = sidecar
        self.pollInterval = pollInterval
        self.errorDuration = errorDuration
        self.sleep = sleep
    }

    public var phase: MenuPhase {
        MenuPhase.derive(sidecar: sidecar.status, health: health, state: state)
    }

    public var activeInput: InputPort? {
        guard state?.app == "com.tcl.tv" else { return nil }
        return inputs.first { $0.active }
    }

    public var isPaired: Bool { health?.tvMac != nil }

    public var showsAdbBanner: Bool {
        guard sidecar.status == .running else { return false }
        return (state?.adbAuth ?? health?.adbAuth) == "pending"
    }

    public var controlsEnabled: Bool { phase == .on || phase == .unknown }

    public func menuOpened() {
        guard pollTask == nil else { return }
        pollTask = Task { [weak self] in
            while !Task.isCancelled {
                guard let self else { return }
                await self.refresh()
                if Task.isCancelled { return }
                let sleep = self.sleep
                let interval = self.pollInterval
                do { try await sleep(interval) } catch { return }
            }
        }
    }

    public func menuClosed() {
        pollTask?.cancel()
        pollTask = nil
    }

    /// Refreshes health and state. Failures are silent and keep the last good values,
    /// except when the sidecar is unreachable: state is cleared and the sidecar source
    /// is asked to recover.
    public func refresh() async {
        var unreachable = false
        do { health = try await api.health() } catch SidecarError.notRunning { unreachable = true } catch {}
        do { state = try await api.state() } catch SidecarError.notRunning { unreachable = true } catch {}
        // Inputs need ADB: polling them in standby only costs connect timeouts.
        if phase == .on {
            let previousActive = inputs.first { $0.active }?.id
            do { inputs = try await api.inputs() } catch SidecarError.notRunning { unreachable = true } catch {}
            if inputs.first(where: { $0.active })?.id != previousActive { picture = nil }
        }
        if unreachable {
            state = nil
            await sidecar.recoverIfUnreachable()
        }
    }

    public func send(key: String) async {
        await perform { try await self.api.key(key) }
    }

    public func launch(_ shortcut: AppShortcut) async {
        await perform { try await self.api.launch(link: shortcut.link) }
    }

    public func selectInput(port: Int) async {
        await perform {
            try await self.api.setInput(port: port)
            self.picture = nil
        }
    }

    public func loadPicture() async {
        pictureLoading = true
        defer { pictureLoading = false }
        do {
            picture = try await api.picture(cached: true)
        } catch is CancellationError {
            return
        } catch {}
        do {
            picture = try await api.picture(cached: false)
        } catch is CancellationError {
            return
        } catch {
            showTransient(userMessage(for: error), code: errorCode(for: error))
        }
    }

    public func setPictureMode(_ label: String) async {
        do {
            let mode = try await api.setPictureMode(label)
            if var p = picture {
                p.mode = mode
                if let m = p.modes.first(where: { $0.label == mode }) { p.modeId = m.id }
                picture = p
            }
        } catch is CancellationError {
            return
        } catch {
            showTransient(userMessage(for: error), code: errorCode(for: error))
        }
    }

    public func setBacklight(_ value: Int) async {
        do {
            let v = try await api.setBacklight(value)
            picture?.backlight = v
        } catch is CancellationError {
            return
        } catch {
            showTransient(userMessage(for: error), code: errorCode(for: error))
        }
    }

    public func pairStart() async -> Bool {
        await pairing { try await self.api.pairStart() }
    }

    public func pairFinish(pin: String) async -> Bool {
        let normalized = pin.trimmingCharacters(in: .whitespacesAndNewlines).uppercased()
        let ok = await pairing { try await self.api.pairFinish(pin: normalized) }
        if ok { await refresh() }
        return ok
    }

    private func perform<T>(_ action: () async throws -> T) async {
        do {
            _ = try await action()
        } catch is CancellationError {
            return
        } catch {
            showTransient(userMessage(for: error), code: errorCode(for: error))
            return
        }
        await refresh()
    }

    private func pairing(_ action: () async throws -> Void) async -> Bool {
        do {
            try await action()
            pairingMessage = nil
            return true
        } catch is CancellationError {
            return false
        } catch {
            if case let SidecarError.api(code, _, _) = error, code == "tv_unreachable" {
                pairingMessage = "TV inacessível — ela está ligada?"
            } else {
                pairingMessage = userMessage(for: error)
            }
            return false
        }
    }

    private func errorCode(for error: Error) -> String? {
        guard let e = error as? SidecarError else { return nil }
        switch e {
        case let .api(code, _, _): return code
        case .notRunning: return "not_running"
        case .timeout: return "timeout"
        case .invalidResponse: return nil
        }
    }

    private func showTransient(_ message: String, code: String?) {
        transientError = message
        lastErrorCode = code
        clearTask?.cancel()
        let sleep = self.sleep
        let duration = errorDuration
        clearTask = Task { [weak self] in
            do { try await sleep(duration) } catch { return }
            guard let self, self.transientError == message else { return }
            self.transientError = nil
            self.lastErrorCode = nil
        }
    }
}
