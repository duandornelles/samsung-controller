import Foundation
import Testing
@testable import TCLCore

actor FakeAPI: SidecarAPI {
    var healthResult: Result<Health, Error> = .success(tvHealth())
    var stateResult: Result<TVState, Error> = .success(tvState("on"))
    var keyResult: Result<String, Error> = .success("remote")
    var launchResult: Result<Void, Error> = .success(())
    var pairStartResult: Result<Void, Error> = .success(())
    var pairFinishResult: Result<Void, Error> = .success(())
    var inputsResult: Result<[InputPort], Error> = .success([])
    var setInputResult: Result<Void, Error> = .success(())
    var pictureCachedResult: Result<PictureState, Error> = .success(testPicture())
    var pictureRealResult: Result<PictureState, Error> = .success(testPicture())
    var setModeResult: Result<String, Error> = .success("Jogo")
    var setBacklightResult: Result<Int, Error> = .success(60)
    private(set) var calls: [String] = []

    func setInputs(_ r: Result<[InputPort], Error>) { inputsResult = r }
    func setSetInput(_ r: Result<Void, Error>) { setInputResult = r }
    func setPicture(cached: Result<PictureState, Error>? = nil, real: Result<PictureState, Error>? = nil) {
        if let cached { pictureCachedResult = cached }
        if let real { pictureRealResult = real }
    }
    func setMode(_ r: Result<String, Error>) { setModeResult = r }

    func set(health: Result<Health, Error>? = nil, state: Result<TVState, Error>? = nil,
             key: Result<String, Error>? = nil, launch: Result<Void, Error>? = nil,
             pairStart: Result<Void, Error>? = nil, pairFinish: Result<Void, Error>? = nil) {
        if let health { healthResult = health }
        if let state { stateResult = state }
        if let key { keyResult = key }
        if let launch { launchResult = launch }
        if let pairStart { pairStartResult = pairStart }
        if let pairFinish { pairFinishResult = pairFinish }
    }

    func count(_ prefix: String) -> Int { calls.filter { $0.hasPrefix(prefix) }.count }

    func health() async throws -> Health { calls.append("health"); return try healthResult.get() }
    func state() async throws -> TVState { calls.append("state"); return try stateResult.get() }
    func pairStart() async throws { calls.append("pairStart"); try pairStartResult.get() }
    func pairFinish(pin: String) async throws { calls.append("pairFinish:\(pin)"); try pairFinishResult.get() }
    func key(_ name: String) async throws -> String { calls.append("key:\(name)"); return try keyResult.get() }
    func launch(link: String) async throws { calls.append("launch:\(link)"); try launchResult.get() }
    func inputs() async throws -> [InputPort] { calls.append("inputs"); return try inputsResult.get() }
    func setInput(port: Int) async throws { calls.append("setInput:\(port)"); try setInputResult.get() }
    func picture(cached: Bool) async throws -> PictureState {
        calls.append("picture:\(cached)")
        return try (cached ? pictureCachedResult : pictureRealResult).get()
    }
    func setPictureMode(_ label: String) async throws -> String { calls.append("setMode:\(label)"); return try setModeResult.get() }
    func setBacklight(_ value: Int) async throws -> Int { calls.append("setBacklight:\(value)"); return try setBacklightResult.get() }
}

func testPicture(mode: String = "Padrão", backlight: Int = 100) -> PictureState {
    PictureState(mode: mode, modeId: "EN_X", modes: [PictureModeOption(id: "EN_X", label: "Padrão"),
                 PictureModeOption(id: "EN_G", label: "Jogo")], backlight: backlight, cachedAt: "2026-10-17T00:00:00+00:00")
}

func testInputs() -> [InputPort] {
    [InputPort(port: 1, id: "a", label: "HDMI 1", connected: true, active: true),
     InputPort(port: 2, id: "b", label: "HDMI 2", connected: false, active: false)]
}

func tvHealth(mac: String? = "AA:BB", adb: String? = "authorized") -> Health {
    Health(ok: true, tvHost: "1.2.3.4", tvMac: mac, channels: Channels(remote: true, adb: true), adbAuth: adb)
}

func tvState(_ power: String?, adb: String? = "authorized") -> TVState {
    TVState(power: power, app: nil, volume: nil, channels: Channels(remote: true, adb: true), adbAuth: adb)
}

@MainActor final class FakeSidecar: SidecarStatusSource {
    var status: SidecarStatus
    private(set) var recoverCalls = 0
    init(_ status: SidecarStatus = .running) { self.status = status }
    func recoverIfUnreachable() async { recoverCalls += 1 }
}

/// Controllable sleep: each call suspends until the test releases it (or the task is cancelled).
@MainActor final class SleepGate {
    private struct Waiter { let id: Int; let duration: Duration; let cont: CheckedContinuation<Void, Error> }
    private var waiters: [Waiter] = []
    private var cancelled: Set<Int> = []
    private var nextID = 0
    private(set) var durations: [Duration] = []

    func sleep(_ d: Duration) async throws {
        let id = nextID
        nextID += 1
        durations.append(d)
        try await withTaskCancellationHandler {
            try await withCheckedThrowingContinuation { (c: CheckedContinuation<Void, Error>) in
                if cancelled.remove(id) != nil || Task.isCancelled {
                    c.resume(throwing: CancellationError())
                } else {
                    waiters.append(Waiter(id: id, duration: d, cont: c))
                }
            }
        } onCancel: {
            Task { @MainActor in self.cancel(id) }
        }
    }

    private func cancel(_ id: Int) {
        if let i = waiters.firstIndex(where: { $0.id == id }) {
            waiters.remove(at: i).cont.resume(throwing: CancellationError())
        } else {
            cancelled.insert(id)
        }
    }

    var pending: Int { waiters.count }

    func waitForPending(_ n: Int, duration: Duration? = nil) async {
        for _ in 0..<10_000 {
            if waiters.filter({ duration == nil || $0.duration == duration }).count >= n { return }
            await Task.yield()
        }
    }

    func release(duration: Duration? = nil) {
        if let i = waiters.firstIndex(where: { duration == nil || $0.duration == duration }) {
            waiters.remove(at: i).cont.resume()
        }
    }
}

@MainActor private func settle() async {
    for _ in 0..<200 { await Task.yield() }
}

@MainActor private func makeStore(
    api: FakeAPI = FakeAPI(), sidecar: FakeSidecar = FakeSidecar(), gate: SleepGate = SleepGate()
) -> (TVStore, FakeAPI, FakeSidecar, SleepGate) {
    let store = TVStore(api: api, sidecar: sidecar, pollInterval: .seconds(3), errorDuration: .seconds(1),
                        sleep: { try await gate.sleep($0) })
    return (store, api, sidecar, gate)
}

@MainActor struct TVStoreTests {
    @Test func phaseTable() {
        let h = tvHealth()
        #expect(MenuPhase.derive(sidecar: .starting, health: h, state: tvState("on")) == .startingSidecar)
        #expect(MenuPhase.derive(sidecar: .failed("boom"), health: h, state: tvState("on")) == .sidecarFailed("boom"))
        #expect(MenuPhase.derive(sidecar: .running, health: tvHealth(mac: nil), state: nil) == .notPaired)
        #expect(MenuPhase.derive(sidecar: .running, health: h, state: tvState("standby")) == .standby)
        #expect(MenuPhase.derive(sidecar: .running, health: h, state: tvState("on")) == .on)
        #expect(MenuPhase.derive(sidecar: .running, health: h, state: nil) == .unknown)
        #expect(MenuPhase.derive(sidecar: .running, health: h, state: tvState(nil)) == .unknown)
        #expect(MenuPhase.derive(sidecar: .running, health: nil, state: nil) == .unknown)
    }

    @Test func notRunningRecoversSidecarAndClearsState() async {
        let (s, api, sidecar, _) = makeStore()
        await s.refresh()
        #expect(s.phase == .on)
        await api.set(health: .failure(SidecarError.notRunning), state: .failure(SidecarError.notRunning))
        await s.refresh()
        #expect(sidecar.recoverCalls == 1)
        #expect(s.state == nil)
        #expect(s.phase == .unknown)
    }

    @Test func otherRefreshFailureDoesNotRecover() async {
        let (s, api, sidecar, _) = makeStore()
        await s.refresh()
        await api.set(health: .failure(SidecarError.timeout), state: .failure(SidecarError.timeout))
        await s.refresh()
        #expect(sidecar.recoverCalls == 0)
        #expect(s.state != nil)
    }

    @Test func lastErrorCodeTracksTransientError() async {
        let (s, api, _, gate) = makeStore()
        #expect(s.lastErrorCode == nil)
        await api.set(key: .failure(SidecarError.api(code: "tv_unreachable", message: "x", status: 503)))
        await s.send(key: "home")
        #expect(s.lastErrorCode == "tv_unreachable")
        await gate.waitForPending(1)
        gate.release()
        await settle()
        #expect(s.transientError == nil)
        #expect(s.lastErrorCode == nil)
        await api.set(key: .failure(SidecarError.notRunning))
        await s.send(key: "home")
        #expect(s.lastErrorCode == "not_running")
        await api.set(key: .failure(SidecarError.timeout))
        await s.send(key: "home")
        #expect(s.lastErrorCode == "timeout")
    }

    @Test func standbyDisablesControls() async {
        let (s, api, _, _) = makeStore()
        await api.set(state: .success(tvState("standby")))
        await s.refresh()
        #expect(s.phase == .standby)
        #expect(!s.controlsEnabled)
        #expect(s.isPaired)
    }

    @Test func adbBannerWhenPending() async {
        let (s, api, sidecar, _) = makeStore()
        await api.set(state: .success(tvState("on", adb: "pending")))
        await s.refresh()
        #expect(s.showsAdbBanner)
        sidecar.status = .failed("x")
        #expect(!s.showsAdbBanner)
    }

    @Test func openStartsPollingCloseStops() async {
        let (s, api, _, gate) = makeStore()
        s.menuOpened()
        await gate.waitForPending(1)
        #expect(await api.count("state") == 1)
        gate.release()
        await gate.waitForPending(1)
        gate.release()
        await gate.waitForPending(1)
        #expect(await api.count("state") == 3)
        #expect(gate.durations.allSatisfy { $0 == .seconds(3) })
        s.menuClosed()
        await settle()
        gate.release()
        await settle()
        #expect(await api.count("state") == 3)
        #expect(s.transientError == nil)
    }

    @Test func doubleOpenSingleLoop() async {
        let (s, api, _, gate) = makeStore()
        s.menuOpened()
        s.menuOpened()
        await gate.waitForPending(1)
        await settle()
        #expect(await api.count("state") == 1)
        #expect(gate.pending == 1)
        s.menuClosed()
    }

    @Test func failedRefreshKeepsLastGoodState() async {
        let (s, api, _, _) = makeStore()
        await s.refresh()
        #expect(s.phase == .on)
        await api.set(health: .failure(SidecarError.timeout), state: .failure(SidecarError.timeout))
        await s.refresh()
        #expect(s.phase == .on)
        #expect(s.health != nil)
        #expect(s.transientError == nil)
    }

    @Test func stateErrorKeepsHealth() async {
        let (s, api, _, _) = makeStore()
        await api.set(state: .failure(SidecarError.timeout))
        await s.refresh()
        #expect(s.health != nil)
        #expect(s.state == nil)
        #expect(s.phase == .unknown)
    }

    @Test func cancellationNeverShownNorClears() async {
        let (s, api, _, _) = makeStore()
        await s.refresh()
        await api.set(health: .failure(CancellationError()), state: .failure(CancellationError()), key: .failure(CancellationError()))
        await s.refresh()
        await s.send(key: "home")
        #expect(s.transientError == nil)
        #expect(s.state != nil)
        #expect(s.health != nil)
    }

    @Test func sendSuccessRefreshes() async {
        let (s, api, _, _) = makeStore()
        await s.send(key: "home")
        let calls = await api.calls
        #expect(calls == ["key:home", "health", "state", "inputs"])
    }

    @Test func launchCallsLinkAndRefreshes() async {
        let (s, api, _, _) = makeStore()
        await s.launch(AppShortcut(name: "YT", link: "https://youtube.com"))
        let calls = await api.calls
        #expect(calls == ["launch:https://youtube.com", "health", "state", "inputs"])
    }

    @Test func sendUnreachableShowsMessageThenClears() async {
        let (s, api, _, gate) = makeStore()
        await api.set(key: .failure(SidecarError.api(code: "tv_unreachable", message: "m", status: 502)))
        await s.send(key: "home")
        #expect(s.transientError == "TV inacessível")
        await gate.waitForPending(1, duration: .seconds(1))
        gate.release(duration: .seconds(1))
        await settle()
        #expect(s.transientError == nil)
    }

    @Test func staleClearDoesNotWipeNewerError() async {
        let (s, api, _, gate) = makeStore()
        await api.set(key: .failure(SidecarError.timeout))
        await s.send(key: "a")
        await gate.waitForPending(1, duration: .seconds(1))
        await api.set(key: .failure(SidecarError.notRunning))
        await s.send(key: "b")
        await settle()
        #expect(s.transientError == "Sidecar não está respondendo")
        #expect(gate.pending == 1)
        gate.release(duration: .seconds(1))
        await settle()
        #expect(s.transientError == nil)
    }

    @Test func sidecarDeadShowsNotResponding() async {
        let (s, api, _, _) = makeStore()
        await api.set(key: .failure(SidecarError.notRunning))
        await s.send(key: "home")
        #expect(s.transientError == "Sidecar não está respondendo")
    }

    @Test func tvTurnsOffWhileOpen() async {
        let (s, api, _, gate) = makeStore()
        s.menuOpened()
        await gate.waitForPending(1)
        #expect(s.phase == .on)
        await api.set(state: .success(tvState("standby")))
        gate.release()
        await gate.waitForPending(1)
        #expect(s.phase == .standby)
        #expect(!s.controlsEnabled)
        s.menuClosed()
    }

    @Test func pairFinishNormalizesPin() async {
        let (s, api, _, _) = makeStore()
        let ok = await s.pairFinish(pin: " 6024f0 ")
        #expect(ok)
        let calls = await api.calls
        #expect(calls == ["pairFinish:6024F0", "health", "state", "inputs"])
    }

    @Test func pairInvalidPinMessage() async {
        let (s, api, _, _) = makeStore()
        await api.set(pairFinish: .failure(SidecarError.api(code: "invalid_pin", message: "m", status: 400)))
        let ok = await s.pairFinish(pin: "AAAAAA")
        #expect(!ok)
        #expect(s.pairingMessage == "PIN incorreto — tente de novo ou peça um novo PIN")
    }

    @Test func pairUnreachableMessage() async {
        let (s, api, _, _) = makeStore()
        await api.set(pairStart: .failure(SidecarError.api(code: "tv_unreachable", message: "m", status: 502)))
        let ok = await s.pairStart()
        #expect(!ok)
        #expect(s.pairingMessage == "TV inacessível — ela está ligada?")
    }

    @Test func pairStartSuccessClearsMessage() async {
        let (s, api, _, _) = makeStore()
        await api.set(pairStart: .failure(SidecarError.timeout))
        _ = await s.pairStart()
        #expect(s.pairingMessage != nil)
        await api.set(pairStart: .success(()))
        #expect(await s.pairStart())
        #expect(s.pairingMessage == nil)
    }

    @Test func refreshUpdatesInputs() async {
        let (s, api, _, _) = makeStore()
        await api.setInputs(.success(testInputs()))
        await s.refresh()
        #expect(s.inputs == testInputs())
        await api.setInputs(.failure(SidecarError.timeout))
        await s.refresh()
        #expect(s.inputs == testInputs())
    }

    @Test func activeInputOnlyWhenOnTVApp() async {
        let (s, api, _, _) = makeStore()
        await api.setInputs(.success(testInputs()))
        await api.set(state: .success(TVState(power: "on", app: "com.tcl.tv", volume: nil,
                                              channels: Channels(remote: true, adb: true), adbAuth: nil)))
        await s.refresh()
        #expect(s.activeInput?.port == 1)
        await api.set(state: .success(TVState(power: "on", app: "com.google.android.youtube.tv", volume: nil,
                                              channels: Channels(remote: true, adb: true), adbAuth: nil)))
        await s.refresh()
        #expect(s.activeInput == nil)
    }

    @Test func selectInputCallsAndRefreshes() async {
        let (s, api, _, _) = makeStore()
        await s.selectInput(port: 2)
        #expect(await api.calls == ["setInput:2", "health", "state", "inputs"])
    }

    @Test func refreshSkipsInputsOutsideOn() async {
        let (s, api, _, _) = makeStore()
        await api.set(state: .success(tvState("standby")))
        await s.refresh()
        #expect(await api.count("inputs") == 0)
        await api.set(state: .success(tvState("on")))
        await s.refresh()
        #expect(await api.count("inputs") == 1)
    }

    @Test func selectInputSuccessClearsPicture() async {
        let (s, _, _, _) = makeStore()
        await s.loadPicture()
        #expect(s.picture != nil)
        await s.selectInput(port: 2)
        #expect(s.picture == nil)
    }

    @Test func selectInputFailureKeepsPicture() async {
        let (s, api, _, _) = makeStore()
        await s.loadPicture()
        await api.setSetInput(.failure(SidecarError.timeout))
        await s.selectInput(port: 2)
        #expect(s.picture != nil)
    }

    @Test func activeInputChangeClearsPicture() async {
        let (s, api, _, _) = makeStore()
        await api.setInputs(.success(testInputs()))
        await s.refresh()
        await s.loadPicture()
        await s.refresh()
        #expect(s.picture != nil)
        var moved = testInputs()
        for i in moved.indices { moved[i].active = (i == 1) }
        await api.setInputs(.success(moved))
        await s.refresh()
        #expect(s.picture == nil)
    }

    @Test func loadPictureUsesCacheThenReal() async {
        let (s, api, _, _) = makeStore()
        await api.setPicture(cached: .success(testPicture(mode: "Cache")), real: .success(testPicture(mode: "Real")))
        await s.loadPicture()
        #expect(await api.calls == ["picture:true", "picture:false"])
        #expect(s.picture?.mode == "Real")
        #expect(!s.pictureLoading)
    }

    @Test func loadPictureNoCacheIsSilent() async {
        let (s, api, _, _) = makeStore()
        await api.setPicture(cached: .failure(SidecarError.api(code: "no_cache", message: "m", status: 404)))
        await s.loadPicture()
        #expect(await api.calls == ["picture:true", "picture:false"])
        #expect(s.transientError == nil)
        #expect(s.picture != nil)
    }

    @Test func loadPictureRealFailureShowsError() async {
        let (s, api, _, _) = makeStore()
        await api.setPicture(real: .failure(SidecarError.api(code: "picture_unreadable", message: "m", status: 502)))
        await s.loadPicture()
        #expect(s.transientError == "m")
        #expect(!s.pictureLoading)
    }

    @Test func setPictureModeUpdatesState() async {
        let (s, _, _, _) = makeStore()
        await s.loadPicture()
        await s.setPictureMode("Jogo")
        #expect(s.picture?.mode == "Jogo")
        #expect(s.picture?.modeId == "EN_G")
    }

    @Test func setBacklightUpdatesState() async {
        let (s, _, _, _) = makeStore()
        await s.loadPicture()
        await s.setBacklight(60)
        #expect(s.picture?.backlight == 60)
    }

    @Test func unknownModeMessage() async {
        let (s, api, _, _) = makeStore()
        await api.setMode(.failure(SidecarError.api(code: "unknown_mode", message: "m", status: 400)))
        await s.setPictureMode("X")
        #expect(s.transientError == "Modo indisponível nesta entrada")
    }
}
