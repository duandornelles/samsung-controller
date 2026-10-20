import Darwin
import Foundation
import Observation

public enum SidecarStatus: Equatable, Sendable {
    case starting, running, failed(String)
}

public protocol SidecarStatusSource: AnyObject {
    @MainActor var status: SidecarStatus { get }
    /// Called when the sidecar stops answering; may relaunch it.
    @MainActor func recoverIfUnreachable() async
}

public protocol LaunchedProcess: AnyObject {
    var isRunning: Bool { get }
    func terminate()
    func kill()
}

public protocol ProcessLauncher {
    func launch(executable: URL, arguments: [String], workingDirectory: URL, logFile: URL,
                onExit: @escaping @Sendable (Int32) -> Void) throws -> LaunchedProcess
}

public struct FoundationProcessLauncher: ProcessLauncher {
    private final class Handle: LaunchedProcess, @unchecked Sendable {
        let process: Process
        init(_ process: Process) { self.process = process }
        var isRunning: Bool { process.isRunning }
        func terminate() { process.terminate() }
        func kill() {
            let pid = process.processIdentifier
            if process.isRunning, pid > 0 { _ = Darwin.kill(pid, SIGKILL) }
        }
    }

    public init() {}

    public func launch(executable: URL, arguments: [String], workingDirectory: URL, logFile: URL,
                       onExit: @escaping @Sendable (Int32) -> Void) throws -> LaunchedProcess {
        let fm = FileManager.default
        try fm.createDirectory(at: logFile.deletingLastPathComponent(), withIntermediateDirectories: true)
        if !fm.fileExists(atPath: logFile.path) {
            fm.createFile(atPath: logFile.path, contents: nil)
        }
        let handle = try FileHandle(forWritingTo: logFile)
        try handle.seekToEnd()

        let process = Process()
        process.executableURL = executable
        process.arguments = arguments
        process.currentDirectoryURL = workingDirectory
        process.standardOutput = handle
        process.standardError = handle
        process.terminationHandler = { p in
            try? handle.close()
            onExit(p.terminationStatus)
        }
        do {
            try process.run()
        } catch {
            try? handle.close()
            throw error
        }
        return Handle(process)
    }
}

@MainActor @Observable
public final class SidecarProcess: SidecarStatusSource {
    public static let defaultUVCandidates: [URL] = [
        URL(fileURLWithPath: "/opt/homebrew/bin/uv"),
        URL(fileURLWithPath: "/usr/local/bin/uv"),
        FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent(".local/bin/uv"),
    ]
    public static let defaultLogFile: URL = FileManager.default.homeDirectoryForCurrentUser
        .appendingPathComponent("Library/Logs/Samsung-controller/sidecar.log")

    private static let maxRestarts = 3
    private static let restartWindow: Duration = .seconds(60)
    private static let healthDeadline: Duration = .seconds(15)
    private static let healthInterval: Duration = .milliseconds(500)
    private static let stopGrace: Duration = .seconds(3)
    private static let stopInterval: Duration = .milliseconds(100)

    public private(set) var status: SidecarStatus = .starting
    public private(set) var ownsProcess = false

    @ObservationIgnored private let api: SidecarAPI
    @ObservationIgnored private let sidecarDirectory: URL
    @ObservationIgnored private let launcher: ProcessLauncher
    @ObservationIgnored private let uvCandidates: [URL]
    @ObservationIgnored private let logFile: URL
    @ObservationIgnored private let fileExists: (String) -> Bool
    @ObservationIgnored private let now: () -> ContinuousClock.Instant
    @ObservationIgnored private let sleep: (Duration) async throws -> Void

    @ObservationIgnored private var process: LaunchedProcess?
    @ObservationIgnored private var generation = 0
    @ObservationIgnored private var stopping = false
    @ObservationIgnored private var restartTimes: [ContinuousClock.Instant] = []

    public init(
        api: SidecarAPI,
        sidecarDirectory: URL,
        launcher: ProcessLauncher = FoundationProcessLauncher(),
        uvCandidates: [URL] = SidecarProcess.defaultUVCandidates,
        logFile: URL = SidecarProcess.defaultLogFile,
        fileExists: @escaping (String) -> Bool = { FileManager.default.fileExists(atPath: $0) },
        now: @escaping () -> ContinuousClock.Instant = { .now },
        sleep: @escaping (Duration) async throws -> Void = { try await Task.sleep(for: $0) }
    ) {
        self.api = api
        self.sidecarDirectory = sidecarDirectory
        self.launcher = launcher
        self.uvCandidates = uvCandidates
        self.logFile = logFile
        self.fileExists = fileExists
        self.now = now
        self.sleep = sleep
    }

    public func start() async {
        // We already hold a live process (booting or running): never launch a second one
        // and never downgrade ownership of the one we have.
        guard process == nil else { return }
        generation += 1
        let myGeneration = generation
        status = .starting
        stopping = false

        if (try? await api.health()) != nil {
            guard generation == myGeneration else { return }
            ownsProcess = false
            status = .running
            return
        }
        guard generation == myGeneration else { return }

        guard fileExists(sidecarDirectory.path) else {
            status = .failed("Pasta do sidecar não encontrada: \(sidecarDirectory.path)")
            return
        }
        guard let uv = uvCandidates.first(where: { fileExists($0.path) }) else {
            status = .failed("uv não encontrado (instale com: brew install uv)")
            return
        }

        let launched: LaunchedProcess
        do {
            launched = try launcher.launch(
                executable: uv, arguments: ["run", "tcl-sidecar"],
                workingDirectory: sidecarDirectory, logFile: logFile,
                onExit: { [weak self] _ in
                    Task { @MainActor [weak self] in await self?.handleExit(generation: myGeneration) }
                })
        } catch {
            status = .failed("Não foi possível iniciar o sidecar: \(error.localizedDescription)")
            return
        }
        process = launched
        ownsProcess = true

        let deadline = now().advanced(by: Self.healthDeadline)
        while now() < deadline {
            if (try? await api.health()) != nil {
                if generation == myGeneration { status = .running }
                return
            }
            // Crash or a newer start()/stop() while probing: that path owns the status now.
            guard generation == myGeneration else { return }
            try? await sleep(Self.healthInterval)
            guard generation == myGeneration else { return }
        }
        generation += 1
        process = nil
        ownsProcess = false
        launched.terminate()
        status = .failed("O sidecar não respondeu em 15 s (veja o log)")
    }

    /// An external sidecar we reused has died: launch our own. No-op if we own the process
    /// (crash handling covers that case).
    public func recoverIfUnreachable() async {
        guard !ownsProcess, status == .running else { return }
        status = .starting
        await start()
    }

    public func retry() async {
        restartTimes = []
        await start()
    }

    public func stop() async {
        generation += 1
        stopping = true
        defer { stopping = false }
        guard ownsProcess, let proc = process else { return }
        process = nil
        ownsProcess = false
        proc.terminate()
        let deadline = now().advanced(by: Self.stopGrace)
        while proc.isRunning, now() < deadline {
            try? await sleep(Self.stopInterval)
        }
        if proc.isRunning { proc.kill() }
    }

    private func handleExit(generation exited: Int) async {
        guard !stopping, exited == generation, process != nil else { return }
        process = nil
        ownsProcess = false
        let t = now()
        restartTimes.removeAll { t - $0 >= Self.restartWindow }
        if restartTimes.count < Self.maxRestarts {
            restartTimes.append(t)
            await start()
        } else {
            status = .failed("O sidecar caiu repetidamente (veja o log)")
        }
    }
}
