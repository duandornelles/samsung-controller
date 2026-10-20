import SwiftUI
import TCLCore

/// Volume −/+ and mute. The level is only shown when the TV reports one (`max > 0`);
/// with the soundbar on ARC the sidecar reports 0/0.
struct VolumeBar: View {
    let store: TVStore

    var body: some View {
        HStack(spacing: 10) {
            Image(systemName: "speaker.wave.2.fill")
                .foregroundStyle(.secondary)
                .accessibilityHidden(true)
            CircleIconButton(symbol: "minus", help: "Diminuir volume") { send("volume_down") }
            Spacer(minLength: 0)
            if let v = store.state?.volume, v.max > 0 {
                Text("\(v.level)/\(v.max)")
                    .font(.callout)
                    .monospacedDigit()
                    .foregroundStyle(.secondary)
                    .contentTransition(.numericText())
                    .accessibilityLabel("Volume \(v.level) de \(v.max)")
            }
            Spacer(minLength: 0)
            CircleIconButton(symbol: "plus", help: "Aumentar volume") { send("volume_up") }
            CircleIconButton(symbol: "speaker.slash.fill", help: "Sem som") { send("mute") }
        }
        .padding(.horizontal, MenuStyle.tilePadding)
        .padding(.vertical, 8)
        .glassEffect(.regular, in: .capsule)
    }

    private func send(_ key: String) {
        Task { await store.send(key: key) }
    }
}
