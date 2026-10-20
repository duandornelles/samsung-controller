import Foundation
import Testing
@testable import TCLCore

final class FakeClock: @unchecked Sendable {
    private let lock = NSLock()
    private var current = ContinuousClock.now
    func now() -> ContinuousClock.Instant { lock.withLock { current } }
    func advance(_ d: Duration) { lock.withLock { current = current.advanced(by: d) } }
}

final class SPFakeAPI: SidecarAPI, @unchecked Sendable {
    private let lock = NSLock()
    private var failuresLeft: Int?   // nil = always fail; 0 = ok
    private var _calls = 0
    var calls: Int { lock.withLock { _calls } }
    init(failures: Int?) { failuresLeft = failures }
    func setFailures(_ n: Int?) { lock.withLock { failuresLeft = n } }
    func health() async throws -> Health {
        let fail: Bool = lock.withLock {
            _calls += 1
            guard let n = failuresLeft else { return true }
            if n > 0 { failuresLeft = n - 1; return true }
            return false
        }
        if fail { throw SidecarError.notRunning }
        return Health(ok: true, tvHost: nil, tvMac: nil, channels: Channels(remote: true, adb: true), adbAuth: nil)
    }
    func state() async throws -> TVState { throw SidecarError.notRunning }
    func pairStart() async throws {}
    func pairFinish(pin: String) async throws {}
    func key(_ name: String) async throws -> String { "" }
    func launch(link: String) async throws {}
    func inputs() async throws -> [InputPort] { [] }
    func setInput(port: Int) async throws {}
    func picture(cached: Bool) async throws -> PictureState { throw SidecarError.notRunning }
    func setPictureMode(_ label: String) async throws -> String { "" }
    func setBacklight(_ value: Int) async throws -> Int { 0 }
}

final class FakeProcess: LaunchedProcess, @unchecked Sendable {
    private let lock = NSLock()
    private var running = true
    private var _terminates = 0, _kills = 0
    let obeysTerminate: Bool
    init(obeysTerminate: Bool) { self.obeysTerminate = obeysTerminate }
    var isRunning: Bool { lock.withLock { running } }
    var terminates: Int { lock.withLock { _terminates } }
    var kills: Int { lock.withLock { _kills } }
    func terminate() { lock.withLock { _terminates += 1; if obeysTerminate { running = false } } }
    func kill() { lock.withLock { _kills += 1; running = false } }
    func die() { lock.withLock { running = false } }
}

final class FakeLauncher: ProcessLauncher, @unchecked Sendable {
    struct Call { let executable: URL; let arguments: [String]; let workingDirectory: URL; let logFile: URL }
    private let lock = NSLock()
    private var _calls: [Call] = []
    private var _processes: [FakeProcess] = []
    private var _exits: [@Sendable (Int32) -> Void] = []
    var obeysTerminate = true
    var calls: [Call] { lock.withLock { _calls } }
    var processes: [FakeProcess] { lock.withLock { _processes } }
    func launch(executable: URL, arguments: [String], workingDirectory: URL, logFile: URL,
                onExit: @escaping @Sendable (Int32) -> Void) throws -> LaunchedProcess {
        let p = FakeProcess(obeysTerminate: obeysTerminate)
        lock.withLock {
            _calls.append(Call(executable: executable, arguments: arguments, workingDirectory: workingDirectory, logFile: logFile))
            _processes.append(p)
            _exits.append(onExit)
        }
        return p
    }
    func crash(_ index: Int) {
        let (p, exit) = lock.withLock { (_processes[index], _exits[index]) }
        p.die()
        exit(1)
    }
}

@MainActor
struct SidecarProcessTests {
    let dir = URL(fileURLWithPath: "/work/sidecar")
    let log = FileManager.default.temporaryDirectory.appendingPathComponent("tcl-test-\(UUID().uuidString)/sidecar.log")

    func make(api: SPFakeAPI, launcher: FakeLauncher, clock: FakeClock,
              exists: @escaping (String) -> Bool = { $0 == "/work/sidecar" || $0 == "/usr/local/bin/uv" },
              directory: URL? = nil,
              sleep: (@Sendable (Duration) async throws -> Void)? = nil) -> SidecarProcess {
        SidecarProcess(
            api: api, sidecarDirectory: directory ?? dir, launcher: launcher,
            uvCandidates: [URL(fileURLWithPath: "/opt/homebrew/bin/uv"), URL(fileURLWithPath: "/usr/local/bin/uv")],
            logFile: log, fileExists: exists, now: { clock.now() },
            sleep: sleep ?? { clock.advance($0) })
    }

    func waitUntil(_ cond: () -> Bool) async {
        for _ in 0..<2000 where !cond() { await Task.yield() }
    }

    @Test func reusesRunningSidecar() async {
        let launcher = FakeLauncher()
        let sp = make(api: SPFakeAPI(failures: 0), launcher: launcher, clock: FakeClock())
        await sp.start()
        #expect(sp.status == .running)
        #expect(sp.ownsProcess == false)
        #expect(launcher.calls.isEmpty)
    }

    @Test func recoverLaunchesOwnWhenExternalDied() async {
        let launcher = FakeLauncher()
        let api = SPFakeAPI(failures: 0)
        let sp = make(api: api, launcher: launcher, clock: FakeClock())
        await sp.start()
        #expect(!sp.ownsProcess)
        api.setFailures(1)
        await sp.recoverIfUnreachable()
        #expect(launcher.calls.count == 1)
        #expect(sp.ownsProcess)
        #expect(sp.status == .running)
    }

    @Test func recoverIsNoOpWhenOwned() async {
        let launcher = FakeLauncher()
        let sp = make(api: SPFakeAPI(failures: 1), launcher: launcher, clock: FakeClock())
        await sp.start()
        #expect(sp.ownsProcess)
        await sp.recoverIfUnreachable()
        #expect(launcher.calls.count == 1)
        #expect(sp.status == .running)
    }

    @Test func stopDoesNotKillReusedSidecar() async {
        let launcher = FakeLauncher()
        let sp = make(api: SPFakeAPI(failures: 0), launcher: launcher, clock: FakeClock())
        await sp.start()
        await sp.stop()
        #expect(launcher.processes.isEmpty)
    }

    @Test func launchesWithAbsoluteUV() async {
        let launcher = FakeLauncher()
        let sp = make(api: SPFakeAPI(failures: 2), launcher: launcher, clock: FakeClock())
        await sp.start()
        #expect(launcher.calls.count == 1)
        #expect(launcher.calls[0].executable == URL(fileURLWithPath: "/usr/local/bin/uv"))
        #expect(launcher.calls[0].arguments == ["run", "tcl-sidecar"])
        #expect(launcher.calls[0].workingDirectory == dir)
        #expect(launcher.calls[0].logFile == log)
        #expect(sp.status == .running)
        #expect(sp.ownsProcess)
    }

    @Test func missingDirectoryFails() async {
        let launcher = FakeLauncher()
        let sp = make(api: SPFakeAPI(failures: nil), launcher: launcher, clock: FakeClock(),
                      exists: { _ in false }, directory: URL(fileURLWithPath: "/x"))
        await sp.start()
        #expect(sp.status == .failed("Pasta do sidecar não encontrada: /x"))
        #expect(launcher.calls.isEmpty)
    }

    @Test func missingUVFails() async {
        let launcher = FakeLauncher()
        let sp = make(api: SPFakeAPI(failures: nil), launcher: launcher, clock: FakeClock(),
                      exists: { $0 == "/work/sidecar" })
        await sp.start()
        #expect(sp.status == .failed("uv não encontrado (instale com: brew install uv)"))
        #expect(launcher.calls.isEmpty)
    }

    @Test func healthTimeoutFails() async {
        let api = SPFakeAPI(failures: nil)
        let sp = make(api: api, launcher: FakeLauncher(), clock: FakeClock())
        await sp.start()
        #expect(sp.status == .failed("O sidecar não respondeu em 15 s (veja o log)"))
        #expect(api.calls >= 30 && api.calls <= 32)
    }

    @Test func restartsOnCrashUpToThreeTimesPerMinute() async {
        let launcher = FakeLauncher()
        let api = SPFakeAPI(failures: nil)
        let sp = make(api: api, launcher: launcher, clock: FakeClock())
        api.setFailures(1)
        await sp.start()
        #expect(sp.status == .running)
        for i in 0..<3 {
            api.setFailures(1)
            launcher.crash(i)
            await waitUntil { launcher.calls.count == i + 2 }
            await waitUntil { sp.status == .running }
            #expect(launcher.calls.count == i + 2)
        }
        api.setFailures(1)
        launcher.crash(3)
        await waitUntil { sp.status != .running }
        #expect(sp.status == .failed("O sidecar caiu repetidamente (veja o log)"))
        #expect(launcher.calls.count == 4)
    }

    @Test func crashesSpreadOverTimeKeepRestarting() async {
        let launcher = FakeLauncher()
        let api = SPFakeAPI(failures: 1)
        let clock = FakeClock()
        let sp = make(api: api, launcher: launcher, clock: clock)
        await sp.start()
        for i in 0..<5 {
            clock.advance(.seconds(61))
            api.setFailures(1)
            launcher.crash(i)
            await waitUntil { launcher.calls.count == i + 2 && sp.status == .running }
            #expect(launcher.calls.count == i + 2)
            #expect(sp.status == .running)
        }
    }

    @Test func retryResetsCounter() async {
        let launcher = FakeLauncher()
        let api = SPFakeAPI(failures: 1)
        let sp = make(api: api, launcher: launcher, clock: FakeClock())
        await sp.start()
        for i in 0..<3 {
            api.setFailures(1)
            launcher.crash(i)
            await waitUntil { launcher.calls.count == i + 2 && sp.status == .running }
        }
        api.setFailures(1)
        launcher.crash(3)
        await waitUntil { sp.status != .running }
        #expect(sp.status == .failed("O sidecar caiu repetidamente (veja o log)"))
        api.setFailures(1)
        await sp.retry()
        #expect(sp.status == .running)
        #expect(launcher.calls.count == 5)
    }

    @Test func stopTerminatesThenKills() async {
        let launcher = FakeLauncher()
        launcher.obeysTerminate = false
        let api = SPFakeAPI(failures: 1)
        let sp = make(api: api, launcher: launcher, clock: FakeClock())
        await sp.start()
        await sp.stop()
        let p = launcher.processes[0]
        #expect(p.terminates == 1)
        #expect(p.kills == 1)
        launcher.crash(0)
        for _ in 0..<50 { await Task.yield() }
        #expect(launcher.calls.count == 1)
    }

    @Test func startDuringHealthPollingLaunchesOnlyOneProcess() async {
        let launcher = FakeLauncher()
        let api = SPFakeAPI(failures: nil)
        let clock = FakeClock()
        let sp = make(api: api, launcher: launcher, clock: clock,
                      sleep: { clock.advance($0); await Task.yield() })
        let first = Task { await sp.start() }
        await waitUntil { launcher.calls.count == 1 }
        await sp.start()
        await sp.retry()
        #expect(launcher.calls.count == 1)
        api.setFailures(0)
        await first.value
        #expect(sp.status == .running)
        #expect(sp.ownsProcess)
        #expect(launcher.calls.count == 1)
    }

    @Test func startWhileOwnedAndRunningKeepsOwnership() async {
        let launcher = FakeLauncher()
        let api = SPFakeAPI(failures: 1)
        let sp = make(api: api, launcher: launcher, clock: FakeClock())
        await sp.start()
        api.setFailures(0)
        await sp.start()
        #expect(sp.ownsProcess)
        #expect(launcher.calls.count == 1)
        await sp.stop()
        #expect(launcher.processes[0].terminates == 1)
    }
}
