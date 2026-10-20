import Foundation
import Testing
@testable import TCLCore

struct ErrorMessagesTests {
    @Test(arguments: [("tv_unreachable", "TV inacessível"), ("not_paired", "Pareamento necessário"),
                      ("adb_unauthorized", "Aceite o pedido de depuração na TV"),
                      ("invalid_pin", "PIN incorreto — tente de novo ou peça um novo PIN"),
                      ("unknown_mode", "Modo indisponível nesta entrada"),
                      ("input_not_confirmed", "A TV não confirmou a troca de entrada")])
    func knownCodes(code: String, expected: String) {
        #expect(userMessage(for: SidecarError.api(code: code, message: "x", status: 502)) == expected)
    }

    @Test func pictureUnreadableUsesServerMessageWithFallback() {
        let e = SidecarError.api(code: "picture_unreadable", message: "A TV não confirmou a alteração", status: 502)
        #expect(userMessage(for: e) == "A TV não confirmou a alteração")
        let empty = SidecarError.api(code: "picture_unreadable", message: "", status: 502)
        #expect(userMessage(for: empty) == "Não foi possível ler a imagem da TV")
    }

    @Test func otherApiUsesServerMessage() {
        let e = SidecarError.api(code: "not_supported", message: "Em investigação (Fase 4)", status: 501)
        #expect(userMessage(for: e) == "Em investigação (Fase 4)")
    }

    @Test func transportErrors() {
        #expect(userMessage(for: SidecarError.notRunning) == "Sidecar não está respondendo")
        #expect(userMessage(for: SidecarError.timeout) == "A TV demorou para responder")
        #expect(userMessage(for: SidecarError.invalidResponse) == "Erro inesperado")
        #expect(userMessage(for: URLError(.badURL)) == "Erro inesperado")
    }
}
