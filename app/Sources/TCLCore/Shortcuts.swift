import Foundation
import Observation

public struct AppShortcut: Codable, Identifiable, Equatable, Sendable {
    public var id: UUID
    public var name: String
    public var link: String

    public init(id: UUID = UUID(), name: String, link: String) {
        self.id = id
        self.name = name
        self.link = link
    }
}

public enum ShortcutError: Error, Equatable {
    case emptyName, invalidLink
}

@MainActor @Observable
public final class ShortcutStore {
    private static let key = "shortcuts"
    @ObservationIgnored private let defaults: UserDefaults
    public private(set) var items: [AppShortcut]

    public init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
        if let data = defaults.data(forKey: Self.key),
           let decoded = try? JSONDecoder().decode([AppShortcut].self, from: data) {
            items = decoded
        } else {
            items = [AppShortcut(name: "YouTube", link: "https://www.youtube.com")]
        }
    }

    public func add(name: String, link: String) throws {
        let trimmed = name.trimmingCharacters(in: .whitespacesAndNewlines)
        let l = link.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { throw ShortcutError.emptyName }
        guard Self.isValidLink(l) else { throw ShortcutError.invalidLink }
        items.append(AppShortcut(name: trimmed, link: l))
        save()
    }

    public func remove(id: UUID) {
        items.removeAll { $0.id == id }
        save()
    }

    public func move(fromOffsets: IndexSet, toOffset: Int) {
        let moving = fromOffsets.map { items[$0] }
        let before = fromOffsets.filter { $0 < toOffset }.count
        var rest = items
        for i in fromOffsets.reversed() { rest.remove(at: i) }
        rest.insert(contentsOf: moving, at: toOffset - before)
        items = rest
        save()
    }

    public static func isValidLink(_ link: String) -> Bool {
        let l = link.trimmingCharacters(in: .whitespacesAndNewlines)
        return l.hasPrefix("http://") || l.hasPrefix("https://") || l.contains("://")
    }

    private func save() {
        if let data = try? JSONEncoder().encode(items) {
            defaults.set(data, forKey: Self.key)
        }
    }
}
