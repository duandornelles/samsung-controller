import AppKit
import SwiftUI
import TCLCore

struct SettingsView: View {
    @Bindable var model: AppModel

    var body: some View {
        TabView(selection: $model.settingsTab) {
            TVSettingsTab(model: model)
                .tabItem { Label("TV", systemImage: "tv") }
                .tag(SettingsTab.tv)
            InputsSettingsTab(store: model.store, names: model.inputNames)
                .tabItem { Label("Entradas", systemImage: "cable.connector") }
                .tag(SettingsTab.inputs)
            ShortcutsSettingsTab(shortcuts: model.shortcuts)
                .tabItem { Label("Atalhos", systemImage: "square.grid.2x2") }
                .tag(SettingsTab.shortcuts)
            SidecarSettingsTab(model: model)
                .tabItem { Label("Sidecar", systemImage: "server.rack") }
                .tag(SettingsTab.sidecar)
        }
        .frame(width: 460, height: 380)
    }
}

// MARK: - TV

private struct TVSettingsTab: View {
    let model: AppModel
    @State private var awaitingPin = false
    @State private var pin = ""
    @State private var busy = false
    @State private var paired = false

    private var store: TVStore { model.store }

    var body: some View {
        Form {
            LabeledContent("IP", value: store.health?.tvHost ?? "—")
            LabeledContent("MAC", value: store.health?.tvMac ?? "—")

            Section {
                Button(store.isPaired ? "Parear de novo" : "Parear") {
                    Task { await startPairing() }
                }
                .disabled(busy)

                if awaitingPin {
                    HStack {
                        TextField("PIN (6 caracteres)", text: $pin)
                            .font(.body.monospaced())
                            .onChange(of: pin) { _, new in
                                let clean = String(new.uppercased().filter { $0.isLetter || $0.isNumber }.prefix(6))
                                if clean != new { pin = clean }
                            }
                            .onSubmit { Task { await confirm() } }
                        Button("Confirmar") { Task { await confirm() } }
                            .disabled(busy || pin.count != 6)
                            .keyboardShortcut(.defaultAction)
                    }
                    Text("Digite o PIN exibido na TV.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }

                if let message = store.pairingMessage {
                    Text(message).foregroundStyle(.red)
                } else if paired {
                    Text("TV pareada.").foregroundStyle(.green)
                }
            }
        }
        .formStyle(.grouped)
        .task { await store.refresh() }
    }

    private func startPairing() async {
        busy = true
        defer { busy = false }
        paired = false
        pin = ""
        awaitingPin = await store.pairStart()
    }

    private func confirm() async {
        guard pin.count == 6, !busy else { return }
        busy = true
        defer { busy = false }
        if await store.pairFinish(pin: pin) {
            awaitingPin = false
            pin = ""
            paired = true
        }
    }
}

// MARK: - Entradas

private struct InputsSettingsTab: View {
    let store: TVStore
    let names: InputNamesStore

    /// Ports reported by the TV, or HDMI 1–4 when it is unavailable.
    private var ports: [Int] {
        let reported = store.inputs.map(\.port)
        return reported.isEmpty ? Array(1...4) : reported.sorted()
    }

    var body: some View {
        Form {
            ForEach(ports, id: \.self) { port in
                Section("HDMI \(port)") {
                    TextField("Nome", text: binding(port, \.name), prompt: Text("HDMI \(port)"))
                    Picker("Símbolo", selection: binding(port, \.symbol)) {
                        ForEach(InputNamesStore.symbols, id: \.self) { symbol in
                            Label(Self.symbolTitle(symbol), systemImage: symbol)
                                .tag(symbol)
                        }
                    }
                    Toggle("Ocultar", isOn: binding(port, \.hidden))
                }
            }
        }
        .formStyle(.grouped)
    }

    private func binding<Value>(_ port: Int, _ keyPath: WritableKeyPath<InputName, Value>) -> Binding<Value> {
        Binding(
            get: { names.name(for: port)[keyPath: keyPath] },
            set: { newValue in
                var value = names.name(for: port)
                value[keyPath: keyPath] = newValue
                names.set(value, for: port)
            }
        )
    }

    private static func symbolTitle(_ symbol: String) -> String {
        switch symbol {
        case "gamecontroller.fill": return "Console"
        case "appletv.fill": return "Apple TV"
        case "laptopcomputer": return "Computador"
        case "tv.fill": return "TV"
        case "hifispeaker.fill": return "Som"
        case "play.rectangle.fill": return "Player"
        case "cable.connector": return "Cabo"
        default: return symbol
        }
    }
}

// MARK: - Atalhos

private struct ShortcutsSettingsTab: View {
    let shortcuts: ShortcutStore
    @State private var name = ""
    @State private var link = ""
    @State private var error: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            List {
                ForEach(shortcuts.items) { item in
                    HStack {
                        VStack(alignment: .leading) {
                            Text(item.name)
                            Text(item.link).font(.caption).foregroundStyle(.secondary).lineLimit(1)
                        }
                        Spacer()
                        Button {
                            shortcuts.remove(id: item.id)
                        } label: {
                            Image(systemName: "trash")
                        }
                        .buttonStyle(.borderless)
                        .help("Remover")
                        .accessibilityLabel("Remover \(item.name)")
                    }
                }
                .onMove { shortcuts.move(fromOffsets: $0, toOffset: $1) }
            }
            .listStyle(.bordered)

            Text("Arraste para reordenar.")
                .font(.caption)
                .foregroundStyle(.secondary)

            HStack {
                TextField("Nome", text: $name)
                    .frame(width: 120)
                TextField("Link (ex.: https://www.youtube.com)", text: $link)
                    .onSubmit(add)
                Button("Adicionar", action: add)
            }
            if let error {
                Text(error).foregroundStyle(.red).font(.callout)
            }
        }
        .padding()
    }

    private func add() {
        do {
            try shortcuts.add(name: name, link: link)
            name = ""
            link = ""
            error = nil
        } catch ShortcutError.emptyName {
            error = "Informe um nome"
        } catch {
            self.error = "Link inválido"
        }
    }
}

// MARK: - Sidecar

private struct SidecarSettingsTab: View {
    let model: AppModel

    var body: some View {
        Form {
            LabeledContent("Pasta") {
                Text(model.configuredDirectory.path)
                    .lineLimit(1)
                    .truncationMode(.middle)
                    .textSelection(.enabled)
            }
            Button("Escolher pasta…", action: chooseFolder)
            if model.needsRestartForDirectory {
                Text("Pasta alterada — reinicie o sidecar para usar a nova pasta.")
                    .foregroundStyle(.orange)
            }

            LabeledContent("Status", value: statusText)

            HStack {
                Button("Reiniciar sidecar") {
                    Task { await model.restartSidecar() }
                }
                .disabled(model.isRestarting)
                Button("Abrir log") {
                    NSWorkspace.shared.open(SidecarProcess.defaultLogFile)
                }
                .disabled(!FileManager.default.fileExists(atPath: SidecarProcess.defaultLogFile.path))
            }
        }
        .formStyle(.grouped)
    }

    private var statusText: String {
        switch model.sidecar.status {
        case .starting: return "Iniciando…"
        case .running:
            return model.sidecar.ownsProcess ? "Rodando (iniciado pelo app)" : "Rodando (externo)"
        case .failed(let reason): return "Parado: \(reason)"
        }
    }

    private func chooseFolder() {
        let panel = NSOpenPanel()
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.allowsMultipleSelection = false
        panel.directoryURL = model.configuredDirectory
        panel.prompt = "Escolher"
        NSApp.activate()
        if panel.runModal() == .OK, let url = panel.url {
            model.setConfiguredDirectory(url)
        }
    }
}
