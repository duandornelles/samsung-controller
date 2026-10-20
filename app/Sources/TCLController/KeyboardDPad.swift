import AppKit
import SwiftUI
import TCLCore

/// Maps arrow keys, Enter and Esc to the TV D-pad while the menu popover is the key window.
///
/// Uses an `NSEvent` local monitor (installed on appear, removed on disappear) instead of
/// `onKeyPress`, because a `MenuBarExtra` window does not reliably give a SwiftUI view focus.
/// Events are only consumed when they target the popover's own window, so other windows
/// (e.g. the Settings PIN field) are unaffected.
///
/// Esc first asks `collapse` to close an expanded module; only when it returns `false`
/// (nothing expanded) is it sent to the TV as "back".
struct KeyboardDPad: ViewModifier {
    let model: AppModel
    let collapse: @MainActor () -> Bool
    @State private var monitor = DPadMonitor()

    func body(content: Content) -> some View {
        content
            .background(WindowReader { monitor.window = $0 })
            .onAppear { monitor.install(model: model, collapse: collapse) }
            .onDisappear { monitor.remove() }
    }
}

extension View {
    func keyboardDPad(model: AppModel, collapse: @escaping @MainActor () -> Bool) -> some View {
        modifier(KeyboardDPad(model: model, collapse: collapse))
    }
}

@MainActor
final class DPadMonitor {
    weak var window: NSWindow?
    private var token: Any?
    private var collapse: (@MainActor () -> Bool)?
    private var throttle = KeyThrottle()

    static func key(for keyCode: UInt16) -> String? {
        switch keyCode {
        case 126: return "up"
        case 125: return "down"
        case 123: return "left"
        case 124: return "right"
        case 36, 76: return "ok"      // Return, keypad Enter
        case 53: return "back"        // Esc
        default: return nil
        }
    }

    func install(model: AppModel, collapse: @escaping @MainActor () -> Bool) {
        self.collapse = collapse
        guard token == nil else { return }
        token = NSEvent.addLocalMonitorForEvents(matching: .keyDown) { [weak self, weak model] event in
            let consumed = MainActor.assumeIsolated { () -> Bool in
                guard let self, let model else { return false }
                return self.handle(keyCode: event.keyCode,
                                   modifiers: event.modifierFlags,
                                   eventWindow: event.window,
                                   model: model)
            }
            return consumed ? nil : event
        }
    }

    func remove() {
        if let token { NSEvent.removeMonitor(token) }
        token = nil
        collapse = nil
    }

    private func handle(keyCode: UInt16, modifiers: NSEvent.ModifierFlags,
                        eventWindow: NSWindow?, model: AppModel) -> Bool {
        guard let window, eventWindow === window else { return false }
        guard modifiers.intersection([.command, .option, .control]).isEmpty else { return false }
        if window.firstResponder is NSTextView { return false }
        guard let key = Self.key(for: keyCode) else { return false }
        if key == "back", collapse?() == true { return true }
        let store = model.store
        guard store.controlsEnabled else { return false }
        if throttle.shouldSend(key, at: .now) {
            Task { await store.send(key: key) }
        }
        return true
    }
}

/// Reports the `NSWindow` hosting the view.
private struct WindowReader: NSViewRepresentable {
    let onWindow: @MainActor (NSWindow?) -> Void

    func makeNSView(context: Context) -> ReaderView {
        let view = ReaderView()
        view.onWindow = onWindow
        return view
    }

    func updateNSView(_ nsView: ReaderView, context: Context) {
        nsView.onWindow = onWindow
    }

    final class ReaderView: NSView {
        var onWindow: (@MainActor (NSWindow?) -> Void)?

        override func viewDidMoveToWindow() {
            super.viewDidMoveToWindow()
            onWindow?(window)
        }
    }
}
