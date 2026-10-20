import Testing
@testable import TCLCore

struct KeyThrottleTests {
    @Test func throttleBlocksFastRepeat() {
        var t = KeyThrottle()
        let t0 = ContinuousClock.now
        let first = t.shouldSend("up", at: t0)
        let fast = t.shouldSend("up", at: t0 + .milliseconds(100))
        let later = t.shouldSend("up", at: t0 + .milliseconds(150))
        #expect(first)
        #expect(!fast)
        #expect(later)
    }

    @Test func throttleKeysAreIndependent() {
        var t = KeyThrottle()
        let t0 = ContinuousClock.now
        let up = t.shouldSend("up", at: t0)
        let down = t.shouldSend("down", at: t0 + .milliseconds(10))
        #expect(up)
        #expect(down)
    }
}
