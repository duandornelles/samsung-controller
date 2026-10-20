import SwiftUI
import TCLCore

/// Picture mode and brightness. Reading opens the TV's own menu, so the state is only
/// read when the module expands (never by polling).
struct PictureModule: View {
    let store: TVStore
    @Binding var expanded: ExpandedModule
    let namespace: Namespace.ID
    @State private var brightness: Double = 50
    @State private var editingBrightness = false
    @State private var pendingMode: String?

    private var isExpanded: Bool { expanded == .picture }

    var body: some View {
        Group {
            if isExpanded { expandedBody } else { compactBody }
        }
        .glassEffectID("picture", in: namespace)
    }

    // MARK: Compact

    private var compactBody: some View {
        Button(action: expand) {
            VStack(alignment: .leading, spacing: 8) {
                ModuleTitle("Imagem")
                HStack(spacing: 8) {
                    Image(systemName: "sun.max.fill")
                        .font(.title3)
                        .foregroundStyle(.yellow)
                        .frame(width: 26, height: 32)
                    Text(store.picture?.mode ?? "Imagem")
                        .font(.body.weight(.medium))
                        .lineLimit(1)
                    Spacer(minLength: 0)
                    Image(systemName: "chevron.right")
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(.tertiary)
                }
            }
            .moduleTile(interactive: true)
        }
        .buttonStyle(.plain)
        .help("Modo de imagem e brilho")
        .accessibilityLabel("Imagem: \(store.picture?.mode ?? "modo desconhecido")")
        .accessibilityHint("Mostra os modos de imagem e o brilho")
    }

    private func expand() {
        withAnimation(MenuStyle.expand) { expanded = .picture }
        guard !store.pictureLoading else { return }
        Task { await store.loadPicture() }
    }

    // MARK: Expanded

    private var expandedBody: some View {
        VStack(alignment: .leading, spacing: 12) {
            ExpandedHeader(title: "Imagem", symbol: "sun.max.fill") {
                withAnimation(MenuStyle.expand) { expanded = .none }
            }
            if store.pictureLoading {
                HStack(spacing: 8) {
                    ProgressView().controlSize(.small)
                    Text("Lendo da TV…")
                        .font(.callout)
                        .foregroundStyle(.secondary)
                }
                .transition(.opacity)
            }
            if let picture = store.picture {
                modes(picture)
                brightnessRow(picture)
            } else if !store.pictureLoading {
                Text("Imagem indisponível")
                    .font(.callout)
                    .foregroundStyle(.secondary)
            }
        }
        .moduleTile()
        .animation(.easeInOut(duration: 0.2), value: store.pictureLoading)
        .onAppear { syncBrightness() }
        .onChange(of: store.picture?.backlight) { _, _ in syncBrightness() }
    }

    private func modes(_ picture: PictureState) -> some View {
        LazyVGrid(columns: [GridItem(.adaptive(minimum: 92), spacing: 6)], spacing: 6) {
            ForEach(picture.modes) { option in
                let isCurrent = option.id == picture.modeId
                Button {
                    setMode(option.label)
                } label: {
                    Group {
                        if pendingMode == option.label {
                            ProgressView().controlSize(.mini)
                        } else {
                            Text(option.label).lineLimit(1)
                        }
                    }
                    .frame(maxWidth: .infinity)
                }
                .buttonStyle(.glass)
                .tint(isCurrent ? Color.accentColor : nil)
                .fontWeight(isCurrent ? .semibold : .regular)
                .accessibilityAddTraits(isCurrent ? .isSelected : [])
            }
        }
        .disabled(store.pictureLoading || pendingMode != nil)
    }

    private func brightnessRow(_ picture: PictureState) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack {
                Text("Brilho")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.secondary)
                Spacer()
                Text("\(Int(brightness))")
                    .font(.caption)
                    .monospacedDigit()
                    .foregroundStyle(.secondary)
                    .contentTransition(.numericText())
            }
            HStack(spacing: 8) {
                Image(systemName: "sun.min")
                    .foregroundStyle(.secondary)
                    .accessibilityHidden(true)
                Slider(value: $brightness, in: 0...100, step: 1) {
                    Text("Brilho")
                } onEditingChanged: { editing in
                    editingBrightness = editing
                    if !editing { commitBrightness() }
                }
                .labelsHidden()
                Image(systemName: "sun.max")
                    .foregroundStyle(.secondary)
                    .accessibilityHidden(true)
            }
        }
        .disabled(store.pictureLoading)
    }

    private func syncBrightness() {
        guard !editingBrightness, let value = store.picture?.backlight else { return }
        brightness = Double(value)
    }

    /// Called once per slider release; sends only if the value changed.
    private func commitBrightness() {
        let value = Int(brightness.rounded())
        guard value != store.picture?.backlight else { return }
        Task {
            await store.setBacklight(value)
            syncBrightness()
        }
    }

    private func setMode(_ label: String) {
        guard pendingMode == nil, label != store.picture?.mode else { return }
        pendingMode = label
        Task {
            await store.setPictureMode(label)
            pendingMode = nil
        }
    }
}
