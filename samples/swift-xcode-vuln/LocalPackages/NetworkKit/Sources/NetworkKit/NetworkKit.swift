import Vapor

public struct NetworkKit {
    public init() {}

    // CVE-2022-24721: FileMiddleware serves files outside the public directory
    public func configure(_ app: Application) {
        app.middleware.use(FileMiddleware(publicDirectory: app.directory.publicDirectory))
    }
}
