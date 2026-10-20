import Foundation
import Testing
@testable import TCLCore

@MainActor struct InputNamesTests {
    private func defaults() -> UserDefaults {
        let name = "InputNamesTests-\(UUID().uuidString)"
        let d = UserDefaults(suiteName: name)!
        d.removePersistentDomain(forName: name)
        return d
    }

    @Test func inputNamesDefaults() {
        let s = InputNamesStore(defaults: defaults())
        #expect(s.name(for: 1) == InputName(name: "HDMI 1", symbol: "cable.connector", hidden: false))
        #expect(s.name(for: 2) == InputName(name: "HDMI 2", symbol: "cable.connector", hidden: false))
        #expect(s.name(for: 3) == InputName(name: "HDMI 3", symbol: "cable.connector", hidden: false))
        #expect(s.name(for: 4) == InputName(name: "HDMI 4", symbol: "cable.connector", hidden: false))
    }

    @Test func inputNamesPersist() {
        let d = defaults()
        let s = InputNamesStore(defaults: d)
        s.set(InputName(name: "Mac", symbol: "laptopcomputer", hidden: true), for: 3)
        #expect(s.name(for: 3).name == "Mac")
        let s2 = InputNamesStore(defaults: d)
        #expect(s2.name(for: 3) == InputName(name: "Mac", symbol: "laptopcomputer", hidden: true))
        #expect(s2.name(for: 1).name == "HDMI 1")
    }

    @Test func symbolsList() {
        #expect(InputNamesStore.symbols == ["gamecontroller.fill", "appletv.fill", "laptopcomputer", "tv.fill",
                                            "hifispeaker.fill", "play.rectangle.fill", "cable.connector"])
    }
}
