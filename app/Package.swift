// swift-tools-version: 6.2
import PackageDescription

let package = Package(
    name: "TCLController",
    platforms: [.macOS(.v26)],
    targets: [
        .target(name: "TCLCore"),
        .executableTarget(name: "TCLController", dependencies: ["TCLCore"]),
        .testTarget(name: "TCLCoreTests", dependencies: ["TCLCore"], resources: [.copy("Fixtures")]),
    ]
)
