import SwiftUI
import TCLCore

/// Active input (compact) or the list of visible HDMI ports (expanded).
struct InputModule: View {
    let store: TVStore
    let names: InputNamesStore
    @Binding var expanded: ExpandedModule
    let namespace: Namespace.ID
    @State private var pendingPort: Int?

    private var isExpanded: Bool { expanded == .input }

    var body: some View {
        Group {
            if isExpanded { expandedBody } else { compactBody }
        }
        .glassEffectID("input", in: namespace)
    }

    // MARK: Compact

    private var compactBody: some View {
        Button {
            withAnimation(MenuStyle.expand) { expanded = .input }
        } label: {
            VStack(alignment: .leading, spacing: 8) {
                ModuleTitle("Entrada")
                HStack(spacing: 8) {
                    Image(systemName: current.symbol)
                        .font(.title3)
                        .frame(width: 26, height: 32)
                        .contentTransition(.symbolEffect(.replace))
                    Text(current.text)
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
        .help("Trocar de entrada")
        .accessibilityLabel("Entrada: \(current.text)")
        .accessibilityHint("Mostra as entradas HDMI")
    }

    private var current: (symbol: String, text: String) {
        guard let input = store.activeInput else { return ("square.grid.2x2.fill", "Apps") }
        let name = names.name(for: input.port)
        return (name.symbol, name.displayName(port: input.port))
    }

    // MARK: Expanded

    private var expandedBody: some View {
        VStack(alignment: .leading, spacing: 10) {
            ExpandedHeader(title: "Entrada", symbol: "cable.connector") {
                withAnimation(MenuStyle.expand) { expanded = .none }
            }
            let ports = visiblePorts
            if ports.isEmpty {
                Text("Nenhuma entrada disponível")
                    .font(.callout)
                    .foregroundStyle(.secondary)
                    .padding(.vertical, 4)
            } else {
                VStack(spacing: 2) {
                    ForEach(ports) { port in
                        row(port)
                    }
                }
            }
        }
        .moduleTile()
    }

    private var visiblePorts: [InputPort] {
        // The active port stays listed even when hidden, so it never vanishes.
        store.inputs.filter { !names.name(for: $0.port).hidden || $0.port == store.activeInput?.port }
    }

    private func row(_ port: InputPort) -> some View {
        let name = names.name(for: port.port)
        let isActive = store.activeInput?.port == port.port
        return Button {
            select(port.port)
        } label: {
            HStack(spacing: 10) {
                Image(systemName: name.symbol)
                    .frame(width: 22)
                    .foregroundStyle(isActive ? Color.accentColor : .primary)
                VStack(alignment: .leading, spacing: 0) {
                    Text(name.displayName(port: port.port))
                        .font(.body.weight(isActive ? .semibold : .regular))
                    Text(port.label)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                if port.connected {
                    Circle()
                        .fill(.green)
                        .frame(width: 7, height: 7)
                        .help("Aparelho conectado")
                }
                Spacer(minLength: 0)
                if pendingPort == port.port {
                    ProgressView().controlSize(.small)
                } else if isActive {
                    Image(systemName: "checkmark")
                        .font(.callout.weight(.semibold))
                        .foregroundStyle(Color.accentColor)
                }
            }
            .padding(.horizontal, 8)
            .padding(.vertical, 6)
            .background(isActive ? AnyShapeStyle(.fill.secondary) : AnyShapeStyle(.clear),
                        in: .rect(cornerRadius: 10))
            .contentShape(.rect(cornerRadius: 10))
        }
        .buttonStyle(.plain)
        .disabled(pendingPort != nil)
        .accessibilityLabel(accessibilityText(name: name, port: port, isActive: isActive))
    }

    private func accessibilityText(name: InputName, port: InputPort, isActive: Bool) -> String {
        var parts = [name.displayName(port: port.port), port.label]
        if port.connected { parts.append("conectado") }
        if isActive { parts.append("ativa") }
        return parts.joined(separator: ", ")
    }

    private func select(_ port: Int) {
        guard pendingPort == nil, store.activeInput?.port != port else { return }
        pendingPort = port
        Task {
            await store.selectInput(port: port)
            pendingPort = nil
        }
    }
}
