import Foundation
import Testing
@testable import TCLCore

final class StubProtocol: URLProtocol, @unchecked Sendable {
    nonisolated(unsafe) static var handler: (@Sendable (URLRequest) throws -> (HTTPURLResponse, Data))?
    nonisolated(unsafe) static var captured: [URLRequest] = []
    nonisolated(unsafe) static var bodies: [Data] = []

    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        var body = request.httpBody
        if body == nil, let s = request.httpBodyStream {
            s.open()
            var data = Data()
            var buf = [UInt8](repeating: 0, count: 1024)
            while s.hasBytesAvailable {
                let n = s.read(&buf, maxLength: buf.count)
                if n <= 0 { break }
                data.append(buf, count: n)
            }
            s.close()
            body = data
        }
        Self.captured.append(request)
        Self.bodies.append(body ?? Data())
        do {
            let (resp, data) = try Self.handler!(request)
            client?.urlProtocol(self, didReceive: resp, cacheStoragePolicy: .notAllowed)
            client?.urlProtocol(self, didLoad: data)
            client?.urlProtocolDidFinishLoading(self)
        } catch {
            client?.urlProtocol(self, didFailWithError: error)
        }
    }
    override func stopLoading() {}
}

private func respond(_ req: URLRequest, _ status: Int, _ body: String) -> (HTTPURLResponse, Data) {
    (HTTPURLResponse(url: req.url!, statusCode: status, httpVersion: nil, headerFields: nil)!, Data(body.utf8))
}

private func fixture(_ name: String) throws -> Data {
    let url = try #require(Bundle.module.url(forResource: name, withExtension: "json", subdirectory: "Fixtures"))
    return try Data(contentsOf: url)
}

private func makeClient(_ handler: @escaping @Sendable (URLRequest) throws -> (HTTPURLResponse, Data)) -> SidecarClient {
    StubProtocol.handler = handler
    StubProtocol.captured = []
    StubProtocol.bodies = []
    let cfg = URLSessionConfiguration.ephemeral
    cfg.protocolClasses = [StubProtocol.self]
    return SidecarClient(session: URLSession(configuration: cfg))
}

@Suite(.serialized) struct SidecarClientTests {
    @Test func decodesRealHealth() throws {
        let d = JSONDecoder()
        d.keyDecodingStrategy = .convertFromSnakeCase
        let h = try d.decode(Health.self, from: fixture("health"))
        #expect(h.ok)
        #expect(h.tvMac != nil)
        #expect(h.tvHost != nil)
        #expect(h.channels == Channels(remote: false, adb: false))
        #expect(h.adbAuth == nil)
    }

    @Test func decodesStateOn() throws {
        let d = JSONDecoder()
        d.keyDecodingStrategy = .convertFromSnakeCase
        let s = try d.decode(TVState.self, from: fixture("state_on"))
        #expect(s.power == "on")
        #expect(s.volume?.max == 100)
        let sb = try d.decode(TVState.self, from: fixture("state_standby"))
        #expect(sb.volume == nil)
    }

    @Test func keyPostsAndReturnsChannel() async throws {
        let c = makeClient { respond($0, 200, #"{"ok":true,"channel":"remote"}"#) }
        let ch = try await c.key("volume_up")
        #expect(ch == "remote")
        #expect(StubProtocol.captured[0].httpMethod == "POST")
        #expect(StubProtocol.captured[0].url?.path == "/key/volume_up")
    }

    @Test func pairFinishSendsPinJSON() async throws {
        let c = makeClient { respond($0, 200, #"{"ok":true}"#) }
        try await c.pairFinish(pin: "6024F0")
        let req = StubProtocol.captured[0]
        #expect(req.value(forHTTPHeaderField: "Content-Type") == "application/json")
        let obj = try JSONSerialization.jsonObject(with: StubProtocol.bodies[0]) as? [String: String]
        #expect(obj == ["pin": "6024F0"])
    }

    @Test func apiErrorIsMapped() async throws {
        let c = makeClient { respond($0, 503, #"{"error":"tv_unreachable","message":"TV inacessivel"}"#) }
        await #expect(throws: SidecarError.api(code: "tv_unreachable", message: "TV inacessivel", status: 503)) {
            _ = try await c.state()
        }
    }

    @Test func nonContractErrorBody() async throws {
        let c = makeClient { respond($0, 500, "boom") }
        await #expect(throws: SidecarError.api(code: "http_500", message: "Erro inesperado (HTTP 500)", status: 500)) {
            _ = try await c.health()
        }
    }

    @Test func connectionRefusedIsNotRunning() async throws {
        let c = makeClient { _ in throw URLError(.cannotConnectToHost) }
        await #expect(throws: SidecarError.notRunning) { _ = try await c.health() }
    }

    @Test func timeoutIsMapped() async throws {
        let c = makeClient { _ in throw URLError(.timedOut) }
        await #expect(throws: SidecarError.timeout) { _ = try await c.health() }
    }

    @Test func cancelledIsCancellationError() async throws {
        let c = makeClient { _ in throw URLError(.cancelled) }
        await #expect(throws: CancellationError.self) { _ = try await c.health() }
    }

    @Test func timeoutsPerRoute() async throws {
        let c = makeClient { req in
            let p = req.url!.path
            if p == "/health" { return respond(req, 200, String(decoding: try fixture("health"), as: UTF8.self)) }
            if p == "/state" { return respond(req, 200, String(decoding: try fixture("state_on"), as: UTF8.self)) }
            return respond(req, 200, #"{"ok":true,"channel":"remote"}"#)
        }
        _ = try await c.health()
        _ = try await c.state()
        _ = try await c.key("power")
        try await c.launch(link: "x")
        try await c.pairStart()
        try await c.pairFinish(pin: "1")
        let t = StubProtocol.captured.map(\.timeoutInterval)
        #expect(t == [5, 5, 30, 30, 30, 30])
    }

    @Test func neverSendsOriginHeader() async throws {
        let c = makeClient { req in
            let p = req.url!.path
            if p == "/health" { return respond(req, 200, String(decoding: try fixture("health"), as: UTF8.self)) }
            if p == "/state" { return respond(req, 200, String(decoding: try fixture("state_on"), as: UTF8.self)) }
            return respond(req, 200, #"{"ok":true,"channel":"remote"}"#)
        }
        _ = try await c.health()
        _ = try await c.state()
        _ = try await c.key("power")
        try await c.launch(link: "x")
        try await c.pairStart()
        try await c.pairFinish(pin: "1")
        #expect(StubProtocol.captured.count == 6)
        for r in StubProtocol.captured { #expect(r.value(forHTTPHeaderField: "Origin") == nil) }
    }

    @Test func decodesInputsAndPicture() throws {
        let d = JSONDecoder()
        d.keyDecodingStrategy = .convertFromSnakeCase
        let ins = try d.decode([InputPort].self, from: fixture("inputs"))
        #expect(ins.count == 4)
        #expect(ins[0].port == 1)
        #expect(ins[0].id == ins[0].id && ins[0].label == "HDMI 1")
        let p = try d.decode(PictureState.self, from: fixture("picture"))
        #expect(p.modes.contains { $0.id == p.modeId })
        #expect(!p.cachedAt.isEmpty)
    }

    @Test func setInputPostsPort() async throws {
        let c = makeClient { respond($0, 200, #"{"ok":true,"active_port":1}"#) }
        try await c.setInput(port: 1)
        #expect(StubProtocol.captured[0].httpMethod == "POST")
        #expect(StubProtocol.captured[0].url?.path == "/input/1")
        #expect(StubProtocol.captured[0].timeoutInterval == 10)
    }

    @Test func inputsGetTimeout() async throws {
        let c = makeClient { respond($0, 200, String(decoding: try fixture("inputs"), as: UTF8.self)) }
        let ins = try await c.inputs()
        #expect(ins.count == 4)
        #expect(StubProtocol.captured[0].url?.path == "/inputs")
        #expect(StubProtocol.captured[0].timeoutInterval == 10)
    }

    @Test func pictureCachedQuery() async throws {
        let c = makeClient { respond($0, 200, String(decoding: try fixture("picture"), as: UTF8.self)) }
        _ = try await c.picture(cached: true)
        _ = try await c.picture(cached: false)
        #expect(StubProtocol.captured[0].url?.path == "/picture")
        #expect(StubProtocol.captured[0].url?.query == "cached=1")
        #expect(StubProtocol.captured[1].url?.query == nil)
        #expect(StubProtocol.captured.map(\.timeoutInterval) == [20, 20])
    }

    @Test func setPictureModeBody() async throws {
        let c = makeClient { respond($0, 200, #"{"ok":true,"mode":"Jogo","mode_id":"EN_TCL_HDR10_GAME"}"#) }
        let m = try await c.setPictureMode("Jogo")
        #expect(m == "Jogo")
        #expect(StubProtocol.captured[0].url?.path == "/picture/mode")
        #expect(StubProtocol.captured[0].timeoutInterval == 20)
        let obj = try JSONSerialization.jsonObject(with: StubProtocol.bodies[0]) as? [String: String]
        #expect(obj == ["mode": "Jogo"])
    }

    @Test func setBacklightBody() async throws {
        let c = makeClient { respond($0, 200, #"{"ok":true,"backlight":60}"#) }
        let v = try await c.setBacklight(60)
        #expect(v == 60)
        #expect(StubProtocol.captured[0].url?.path == "/picture/backlight")
        #expect(StubProtocol.captured[0].timeoutInterval == 20)
        let obj = try JSONSerialization.jsonObject(with: StubProtocol.bodies[0]) as? [String: Int]
        #expect(obj == ["value": 60])
    }
}
