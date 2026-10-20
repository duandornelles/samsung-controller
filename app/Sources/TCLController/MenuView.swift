import AppKit
import SwiftUI
import TCLCore

/// Which module of the menu is expanded (at most one at a time).
enum ExpandedModule: Hashable, Sendable {
    case none, input, picture
}

/// Shared look of the menu: corner radius, spacing and animation.
enum MenuStyle {
    static let width: CGFloat = 340
    static let spacing: CGFloat = 10
    static let cornerRadius: CGFloat = 18
    static let tilePadding: CGFloat = 12
    static let expand: Animation = .spring(duration: 0.35, bounce: 0.15)
}

struct MenuView: View {
    let model: AppModel
    @Environment(\.openSettings) private var openSettings
    @State private var expanded: ExpandedModule = .none
    @Namespace private var glass

    private var store: TVStore { model.store }

    var body: some View {
        GlassEffectContainer(spacing: MenuStyle.spacing) {
            VStack(alignment: .leading, spacing: MenuStyle.spacing) {
                MenuHeader(store: store, names: model.inputNames)
                phaseContent
                footer
            }
        }
        .padding(14)
        .frame(width: MenuStyle.width)
        .animation(MenuStyle.expand, value: expanded)
        .keyboardDPad(model: model, collapse: collapseExpanded)
        .onAppear { store.menuOpened() }
        .onDisappear {
            store.menuClosed()
            expanded = .none
        }
        .onChange(of: store.controlsEnabled) { _, enabled in
            if !enabled { expanded = .none }
        }
    }

    /// Collapses the expanded module. Returns `false` when nothing was expanded.
    private func collapseExpanded() -> Bool {
        guard expanded != .none else { return false }
        withAnimation(MenuStyle.expand) { expanded = .none }
        return true
    }

    // MARK: - Phase

    @ViewBuilder
    private var phaseContent: some View {
        switch store.phase {
        case .startingSidecar:
            StatusCard(text: "Conectando…", showsProgress: true)
        case .sidecarFailed(let reason):
            StatusCard(symbol: "exclamationmark.triangle.fill", tint: .red,
                       text: "Sidecar parado: \(reason)") {
                Button("Tentar de novo") {
                    Task {
                        await model.sidecar.retry()
                        await model.store.refresh()
                    }
                }
                .buttonStyle(.glassProminent)
                Button("Ajustes") { showSettings(tab: .sidecar) }
                    .buttonStyle(.glass)
            }
        case .notPaired:
            adbBanner
            StatusCard(symbol: "link", text: "TV não pareada") {
                Button("Parear TV") { showSettings(tab: .tv) }
                    .buttonStyle(.glassProminent)
            }
        case .standby:
            adbBanner
            StatusCard(symbol: "moon.zzz.fill", text: "Em espera · ligue pelo controle físico")
        case .on, .unknown:
            adbBanner
            modules
        }
    }

    @ViewBuilder
    private var adbBanner: some View {
        if store.showsAdbBanner {
            Label("Aceite o pedido de depuração na TV", systemImage: "exclamationmark.shield.fill")
                .font(.callout)
                .symbolRenderingMode(.multicolor)
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.horizontal, MenuStyle.tilePadding)
                .padding(.vertical, 9)
                .glassEffect(.regular.tint(.yellow.opacity(0.35)), in: .rect(cornerRadius: 14))
                .glassEffectID("adb", in: glass)
        }
    }

    // MARK: - Modules

    private var modules: some View {
        VStack(spacing: MenuStyle.spacing) {
            switch expanded {
            case .none:
                HStack(alignment: .top, spacing: MenuStyle.spacing) {
                    ControlsModule(store: store)
                        .glassEffectID("controls", in: glass)
                    InputModule(store: store, names: model.inputNames, expanded: $expanded,
                                namespace: glass)
                }
                .fixedSize(horizontal: false, vertical: true)
                HStack(alignment: .top, spacing: MenuStyle.spacing) {
                    PictureModule(store: store, expanded: $expanded, namespace: glass)
                    AppsModule(store: store, shortcuts: model.shortcuts)
                        .glassEffectID("apps", in: glass)
                }
                .fixedSize(horizontal: false, vertical: true)
            case .input:
                InputModule(store: store, names: model.inputNames, expanded: $expanded,
                            namespace: glass)
            case .picture:
                PictureModule(store: store, expanded: $expanded, namespace: glass)
            }
            VolumeBar(store: store)
                .glassEffectID("volume", in: glass)
        }
        .disabled(!store.controlsEnabled)
    }

    // MARK: - Footer

    private var footer: some View {
        VStack(alignment: .leading, spacing: 8) {
            if let error = store.transientError {
                Label(error, systemImage: "exclamationmark.circle.fill")
                    .font(.callout)
                    .foregroundStyle(.red)
                    .fixedSize(horizontal: false, vertical: true)
                    .transition(.opacity)
            }
            HStack(spacing: 8) {
                Text("⌨ setas/Enter/Esc = D-pad")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                Spacer()
                footerButton("Ajustes", symbol: "gearshape") { showSettings(tab: nil) }
                footerButton("Sair", symbol: "eject") { NSApp.terminate(nil) }
            }
            .padding(.leading, 4)
        }
        .animation(.easeInOut(duration: 0.2), value: store.transientError)
    }

    private func footerButton(_ title: String, symbol: String,
                              action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Image(systemName: symbol)
                .frame(width: 16, height: 16)
        }
        .buttonStyle(.glass)
        .buttonBorderShape(.circle)
        .help(title)
        .accessibilityLabel(title)
    }

    private func showSettings(tab: SettingsTab?) {
        if let tab { model.settingsTab = tab }
        NSApp.activate()
        openSettings()
        NSApp.activate()
    }
}

// MARK: - Header

/// `TV · ● <status> · <symbol> <active input>`.
private struct MenuHeader: View {
    let store: TVStore
    let names: InputNamesStore

    var body: some View {
        HStack(spacing: 6) {
            Image(systemName: store.phase == .on ? "tv.fill" : "tv")
                .contentTransition(.symbolEffect(.replace))
            Text("TV")
                .fontWeight(.semibold)
            separator
            Circle()
                .fill(statusColor)
                .frame(width: 8, height: 8)
                .accessibilityHidden(true)
            Text(statusText)
                .layoutPriority(1)
            if let detail {
                separator
                if let symbol = detail.symbol {
                    Image(systemName: symbol)
                        .foregroundStyle(.secondary)
                        .contentTransition(.symbolEffect(.replace))
                }
                Text(detail.text)
                    .lineLimit(1)
                    .truncationMode(.middle)
            }
            Spacer(minLength: 0)
        }
        .font(.headline)
        .padding(.horizontal, 4)
        .help(store.health?.tvHost.map { "TV \($0)" } ?? "TV")
        .accessibilityElement(children: .combine)
    }

    private var separator: some View {
        Text("·").foregroundStyle(.tertiary).accessibilityHidden(true)
    }

    private var statusText: String {
        switch store.phase {
        case .on: return "Ligada"
        case .standby: return "Em espera"
        case .unknown: return "Verificando…"
        case .startingSidecar: return "Conectando…"
        case .sidecarFailed: return "Sidecar parado"
        case .notPaired: return "Não pareada"
        }
    }

    private var statusColor: Color {
        switch store.phase {
        case .on: return .green
        case .standby, .unknown, .startingSidecar: return .secondary
        case .sidecarFailed: return .red
        case .notPaired: return .orange
        }
    }

    /// Active input (friendly name) or, outside the HDMI inputs, a generic label (never a raw package name).
    private var detail: (symbol: String?, text: String)? {
        guard store.phase == .on else { return nil }
        if let input = store.activeInput {
            let name = names.name(for: input.port)
            return (name.symbol, name.displayName(port: input.port))
        }
        if let app = store.state?.app, !app.isEmpty {
            return (nil, app == "com.tcl.tv" ? "TV" : "Apps")
        }
        return nil
    }
}

extension InputName {
    /// Name shown in the UI; falls back to "HDMI N" when the user cleared it.
    func displayName(port: Int) -> String {
        let trimmed = name.trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.isEmpty ? "HDMI \(port)" : trimmed
    }
}

// MARK: - Shared module chrome

/// Glass tile used by every module of the menu.
struct ModuleTile: ViewModifier {
    var interactive = false

    func body(content: Content) -> some View {
        content
            .padding(MenuStyle.tilePadding)
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
            .contentShape(.rect(cornerRadius: MenuStyle.cornerRadius))
            .glassEffect(interactive ? .regular.interactive() : .regular,
                         in: .rect(cornerRadius: MenuStyle.cornerRadius))
    }
}

extension View {
    func moduleTile(interactive: Bool = false) -> some View {
        modifier(ModuleTile(interactive: interactive))
    }
}

/// Small caption shown at the top of each tile.
struct ModuleTitle: View {
    let title: String

    init(_ title: String) { self.title = title }

    var body: some View {
        Text(title)
            .font(.caption.weight(.semibold))
            .foregroundStyle(.secondary)
            .textCase(nil)
    }
}

/// Title row of an expanded module, with a collapse button.
struct ExpandedHeader: View {
    let title: String
    let symbol: String
    let collapse: () -> Void

    var body: some View {
        HStack(spacing: 8) {
            Image(systemName: symbol)
                .foregroundStyle(.secondary)
            Text(title)
                .font(.headline)
            Spacer()
            Button(action: collapse) {
                Image(systemName: "chevron.up")
                    .font(.callout.weight(.semibold))
                    .frame(width: 14, height: 14)
            }
            .buttonStyle(.glass)
            .buttonBorderShape(.circle)
            .help("Recolher (Esc)")
            .accessibilityLabel("Recolher")
        }
    }
}

/// Round icon button used inside tiles.
struct CircleIconButton: View {
    let symbol: String
    let help: String
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Image(systemName: symbol)
                .font(.system(.body, weight: .semibold))
                .frame(width: 32, height: 32)
                .background(.fill.tertiary, in: .circle)
                .contentShape(.circle)
        }
        .buttonStyle(.plain)
        .help(help)
        .accessibilityLabel(help)
    }
}
