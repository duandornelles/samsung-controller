import Foundation

public func userMessage(for error: Error) -> String {
    guard let e = error as? SidecarError else { return "Erro inesperado" }
    switch e {
    case let .api(code, message, _):
        switch code {
        case "tv_unreachable": return "TV inacessível"
        case "not_paired": return "Pareamento necessário"
        case "adb_unauthorized": return "Aceite o pedido de depuração na TV"
        case "invalid_pin": return "PIN incorreto — tente de novo ou peça um novo PIN"
        case "unknown_mode": return "Modo indisponível nesta entrada"
        case "input_not_confirmed": return "A TV não confirmou a troca de entrada"
        case "picture_unreadable": return message.isEmpty ? "Não foi possível ler a imagem da TV" : message
        default: return message
        }
    case .notRunning: return "Sidecar não está respondendo"
    case .timeout: return "A TV demorou para responder"
    case .invalidResponse: return "Erro inesperado"
    }
}
