import AppKit
import SwiftUI
import TCLCore

@main
struct TCLControllerApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate

    var body: some Scene {
        MenuBarExtra {
            MenuView(model: appDelegate.model)
        } label: {
            MenuBarIcon(model: appDelegate.model)
        }
        .menuBarExtraStyle(.window)

        Settings {
            SettingsView(model: appDelegate.model)
        }
    }
}

/// Separate view so the icon re-renders through Observation tracking.
private struct MenuBarIcon: View {
    let model: AppModel

    var body: some View {
        Image(systemName: model.iconName)
    }
}

@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate {
    let model = AppModel()
    private var terminating = false

    func applicationDidFinishLaunching(_ notification: Notification) {
        Task {
            await model.sidecar.start()
            await model.store.refresh()
        }
    }

    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        guard !terminating else { return .terminateLater }
        terminating = true
        model.store.menuClosed()
        Task {
            // Only terminates the sidecar if this app launched it (SidecarProcess.ownsProcess).
            await model.sidecar.stop()
            NSApp.reply(toApplicationShouldTerminate: true)
        }
        return .terminateLater
    }
}

enum SettingsTab: Hashable {
    case tv, inputs, shortcuts, sidecar
}

@MainActor @Observable
final class AppModel {
    static let directoryKey = "sidecarDirectory"
    static let defaultDirectory: URL = FileManager.default.homeDirectoryForCurrentUser
        .appendingPathComponent("Documents/Projetos/Samsung-controller/sidecar")

    let shortcuts = ShortcutStore()
    let inputNames = InputNamesStore()
    private(set) var sidecar: SidecarProcess
    private(set) var store: TVStore
    /// Directory the current `sidecar` was created with.
    private(set) var activeDirectory: URL
    /// Directory saved in UserDefaults (may differ from `activeDirectory` until restart).
    private(set) var configuredDirectory: URL
    private(set) var isRestarting = false
    var settingsTab: SettingsTab = .tv

    @ObservationIgnored private let client = SidecarClient()
    @ObservationIgnored private let defaults: UserDefaults

    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
        let dir = Self.savedDirectory(defaults)
        let sidecar = SidecarProcess(api: client, sidecarDirectory: dir)
        self.sidecar = sidecar
        self.store = TVStore(api: client, sidecar: sidecar)
        self.activeDirectory = dir
        self.configuredDirectory = dir
    }

    var needsRestartForDirectory: Bool {
        configuredDirectory.standardizedFileURL != activeDirectory.standardizedFileURL
    }

    var iconName: String {
        if case .sidecarFailed = store.phase { return "exclamationmark.triangle" }
        if lastCommandUnreachable { return "exclamationmark.triangle" }
        return store.phase == .on ? "tv.fill" : "tv"
    }

    private var lastCommandUnreachable: Bool {
        store.lastErrorCode == "tv_unreachable"
    }

    func setConfiguredDirectory(_ url: URL) {
        configuredDirectory = url
        defaults.set(url.path, forKey: Self.directoryKey)
    }

    /// Restarts the sidecar. If the configured directory changed, recreates the
    /// sidecar process and store so the new directory takes effect.
    func restartSidecar() async {
        guard !isRestarting else { return }
        isRestarting = true
        defer { isRestarting = false }
        await sidecar.stop()
        if needsRestartForDirectory {
            store.menuClosed()
            let dir = configuredDirectory
            let newSidecar = SidecarProcess(api: client, sidecarDirectory: dir)
            sidecar = newSidecar
            store = TVStore(api: client, sidecar: newSidecar)
            activeDirectory = dir
            await newSidecar.start()
        } else {
            await sidecar.retry()
        }
        await store.refresh()
    }

    private static func savedDirectory(_ defaults: UserDefaults) -> URL {
        if let path = defaults.string(forKey: directoryKey), !path.isEmpty {
            return URL(fileURLWithPath: path, isDirectory: true)
        }
        return defaultDirectory
    }
}
