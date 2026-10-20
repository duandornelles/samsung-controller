import Foundation

public protocol SidecarAPI: Sendable {
    func health() async throws -> Health
    func state() async throws -> TVState
    func pairStart() async throws
    func pairFinish(pin: String) async throws
    func key(_ name: String) async throws -> String
    func launch(link: String) async throws
    func inputs() async throws -> [InputPort]
    func setInput(port: Int) async throws
    func picture(cached: Bool) async throws -> PictureState
    func setPictureMode(_ label: String) async throws -> String
    func setBacklight(_ value: Int) async throws -> Int
}

public final class SidecarClient: SidecarAPI {
    private struct ErrorBody: Decodable {
        let error: String
        let message: String
    }
    private struct KeyResponse: Decodable {
        let channel: String
    }

    private struct ModeResponse: Decodable {
        let mode: String
    }
    private struct BacklightResponse: Decodable {
        let backlight: Int
    }

    private let baseURL: URL
    private let session: URLSession

    public init(baseURL: URL = URL(string: "http://127.0.0.1:8766")!, session: URLSession = .shared) {
        self.baseURL = baseURL
        self.session = session
    }

    public func health() async throws -> Health {
        try decode(Health.self, from: await send("GET", "health", timeout: 5))
    }

    public func state() async throws -> TVState {
        try decode(TVState.self, from: await send("GET", "state", timeout: 5))
    }

    public func pairStart() async throws {
        _ = try await send("POST", "pair/start", timeout: 30)
    }

    public func pairFinish(pin: String) async throws {
        _ = try await send("POST", "pair/finish", body: ["pin": pin], timeout: 30)
    }

    public func key(_ name: String) async throws -> String {
        let data = try await send("POST", "key", name, timeout: 30)
        return try decode(KeyResponse.self, from: data).channel
    }

    public func launch(link: String) async throws {
        _ = try await send("POST", "app", body: ["link": link], timeout: 30)
    }

    public func inputs() async throws -> [InputPort] {
        try decode([InputPort].self, from: await send("GET", "inputs", timeout: 10))
    }

    public func setInput(port: Int) async throws {
        _ = try await send("POST", "input", String(port), timeout: 10)
    }

    public func picture(cached: Bool) async throws -> PictureState {
        let data = try await send("GET", "picture", query: cached ? [URLQueryItem(name: "cached", value: "1")] : nil, timeout: 20)
        return try decode(PictureState.self, from: data)
    }

    public func setPictureMode(_ label: String) async throws -> String {
        let data = try await send("POST", "picture", "mode", body: ["mode": label], timeout: 20)
        return try decode(ModeResponse.self, from: data).mode
    }

    public func setBacklight(_ value: Int) async throws -> Int {
        let data = try await send("POST", "picture", "backlight", body: ["value": value], timeout: 20)
        return try decode(BacklightResponse.self, from: data).backlight
    }

    private func decode<T: Decodable>(_ type: T.Type, from data: Data) throws -> T {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        do {
            return try decoder.decode(type, from: data)
        } catch {
            throw SidecarError.invalidResponse
        }
    }

    private func send(
        _ method: String,
        _ components: String...,
        query: [URLQueryItem]? = nil,
        body: [String: any Sendable]? = nil,
        timeout: TimeInterval
    ) async throws -> Data {
        var url = baseURL
        for c in components.flatMap({ $0.split(separator: "/").map(String.init) }) {
            url = url.appendingPathComponent(c)
        }
        if let query, var c = URLComponents(url: url, resolvingAgainstBaseURL: false) {
            c.queryItems = query
            url = c.url ?? url
        }
        var request = URLRequest(url: url, timeoutInterval: timeout)
        request.httpMethod = method
        if let body {
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = try JSONSerialization.data(withJSONObject: body)
        }

        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await session.data(for: request)
        } catch let error as URLError {
            switch error.code {
            case .cannotConnectToHost, .cannotFindHost, .networkConnectionLost, .notConnectedToInternet:
                throw SidecarError.notRunning
            case .timedOut:
                throw SidecarError.timeout
            case .cancelled:
                throw CancellationError()
            default:
                throw SidecarError.invalidResponse
            }
        }
        guard let http = response as? HTTPURLResponse else { throw SidecarError.invalidResponse }
        guard (200..<300).contains(http.statusCode) else {
            if let e = try? JSONDecoder().decode(ErrorBody.self, from: data) {
                throw SidecarError.api(code: e.error, message: e.message, status: http.statusCode)
            }
            throw SidecarError.api(
                code: "http_\(http.statusCode)",
                message: "Erro inesperado (HTTP \(http.statusCode))",
                status: http.statusCode
            )
        }
        return data
    }
}
