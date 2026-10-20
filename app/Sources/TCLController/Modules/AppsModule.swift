import SwiftUI
import TCLCore

/// App shortcuts (configured in Settings › Atalhos).
struct AppsModule: View {
    let store: TVStore
    let shortcuts: ShortcutStore

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            ModuleTitle("Apps")
            if shortcuts.items.isEmpty {
                Text("Nenhum atalho (adicione em Ajustes)")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            } else {
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: 6) {
                        ForEach(shortcuts.items) { shortcut in
                            Button {
                                Task { await store.launch(shortcut) }
                            } label: {
                                Label(shortcut.name, systemImage: "play.fill")
                                    .labelStyle(AppChipLabelStyle())
                            }
                            .buttonStyle(.plain)
                            .help(shortcut.link)
                        }
                    }
                }
            }
        }
        .moduleTile()
    }
}

private struct AppChipLabelStyle: LabelStyle {
    func makeBody(configuration: Configuration) -> some View {
        HStack(spacing: 4) {
            configuration.icon.font(.caption2)
            configuration.title.font(.callout).lineLimit(1)
        }
        .padding(.horizontal, 10)
        .frame(height: 32)
        .background(.fill.tertiary, in: .capsule)
        .contentShape(.capsule)
    }
}
