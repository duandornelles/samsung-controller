import SwiftUI

/// Glass card for the phases where the TV modules are not shown
/// (connecting, sidecar stopped, not paired, standby).
struct StatusCard<Actions: View>: View {
    var symbol: String?
    var tint: Color?
    let text: String
    var showsProgress = false
    @ViewBuilder var actions: Actions

    init(symbol: String? = nil, tint: Color? = nil, text: String, showsProgress: Bool = false,
         @ViewBuilder actions: () -> Actions) {
        self.symbol = symbol
        self.tint = tint
        self.text = text
        self.showsProgress = showsProgress
        self.actions = actions()
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(alignment: .firstTextBaseline, spacing: 10) {
                if showsProgress {
                    ProgressView().controlSize(.small)
                } else if let symbol {
                    Image(systemName: symbol)
                        .foregroundStyle(tint ?? .secondary)
                        .accessibilityHidden(true)
                }
                Text(text)
                    .fixedSize(horizontal: false, vertical: true)
            }
            HStack(spacing: 8) { actions }
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .glassEffect(.regular, in: .rect(cornerRadius: MenuStyle.cornerRadius))
    }
}

extension StatusCard where Actions == EmptyView {
    init(symbol: String? = nil, tint: Color? = nil, text: String, showsProgress: Bool = false) {
        self.init(symbol: symbol, tint: tint, text: text, showsProgress: showsProgress) { EmptyView() }
    }
}
