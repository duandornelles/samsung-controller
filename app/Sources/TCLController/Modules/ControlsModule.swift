import SwiftUI
import TCLCore

/// Power, Home and Back.
struct ControlsModule: View {
    let store: TVStore

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            ModuleTitle("Controles")
            HStack(spacing: 0) {
                key("power", symbol: "power", help: "Desligar")
                Spacer(minLength: 4)
                key("home", symbol: "house.fill", help: "Início")
                Spacer(minLength: 4)
                key("back", symbol: "arrow.uturn.backward", help: "Voltar")
            }
        }
        .moduleTile()
    }

    private func key(_ key: String, symbol: String, help: String) -> some View {
        CircleIconButton(symbol: symbol, help: help) {
            Task { await store.send(key: key) }
        }
    }
}
