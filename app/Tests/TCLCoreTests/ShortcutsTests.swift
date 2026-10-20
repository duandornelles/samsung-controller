import Foundation
import Testing
@testable import TCLCore

@MainActor
struct ShortcutsTests {
    private func makeDefaults() -> (UserDefaults, String) {
        let name = UUID().uuidString
        return (UserDefaults(suiteName: name)!, name)
    }

    @Test func defaultShortcutIsYouTube() {
        let (d, name) = makeDefaults()
        defer { d.removePersistentDomain(forName: name) }
        let s = ShortcutStore(defaults: d)
        #expect(s.items.count == 1)
        #expect(s.items[0].name == "YouTube")
        #expect(s.items[0].link == "https://www.youtube.com")
    }

    @Test func addPersistsAcrossInstances() throws {
        let (d, name) = makeDefaults()
        defer { d.removePersistentDomain(forName: name) }
        let s = ShortcutStore(defaults: d)
        try s.add(name: "Netflix", link: "https://www.netflix.com")
        let s2 = ShortcutStore(defaults: d)
        #expect(s2.items.map(\.name) == ["YouTube", "Netflix"])
        #expect(s2.items[1].link == "https://www.netflix.com")
    }

    @Test func rejectsInvalidInput() {
        let (d, name) = makeDefaults()
        defer { d.removePersistentDomain(forName: name) }
        let s = ShortcutStore(defaults: d)
        #expect(throws: ShortcutError.emptyName) { try s.add(name: "  ", link: "https://x") }
        #expect(throws: ShortcutError.invalidLink) { try s.add(name: "X", link: "netflix") }
        #expect(s.items.count == 1)
    }

    @Test func removeAndMovePersist() throws {
        let (d, name) = makeDefaults()
        defer { d.removePersistentDomain(forName: name) }
        let s = ShortcutStore(defaults: d)
        try s.add(name: "A", link: "https://a.com")
        try s.add(name: "B", link: "myapp://b")
        s.move(fromOffsets: IndexSet(integer: 2), toOffset: 0)
        #expect(ShortcutStore(defaults: d).items.map(\.name) == ["B", "YouTube", "A"])
        let youtube = s.items[1].id
        s.remove(id: youtube)
        #expect(ShortcutStore(defaults: d).items.map(\.name) == ["B", "A"])
    }

    @Test func emptyListStaysEmpty() {
        let (d, name) = makeDefaults()
        defer { d.removePersistentDomain(forName: name) }
        let s = ShortcutStore(defaults: d)
        for item in s.items { s.remove(id: item.id) }
        #expect(ShortcutStore(defaults: d).items == [])
    }
}
