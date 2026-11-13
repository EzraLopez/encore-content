// Signs a MusicKit developer token (ES256 JWT) from a MusicKit .p8 key.
// Usage: swift tools/musickit_token.swift <AuthKey.p8> <keyId> <teamId> [days]
// Prints only the token; pipe it where it's needed (APPLE_MUSIC_TOKEN),
// never into a file in this repo. Apple allows up to 180 days.
import CryptoKit
import Foundation

let args = CommandLine.arguments
guard args.count >= 4 else {
    FileHandle.standardError.write(Data("usage: musickit_token.swift <AuthKey.p8> <keyId> <teamId> [days]\n".utf8))
    exit(2)
}
let pem = try String(contentsOfFile: args[1], encoding: .utf8)
let key = try P256.Signing.PrivateKey(pemRepresentation: pem)
let days = args.count > 4 ? Double(args[4]) ?? 180 : 180
let now = Int(Date().timeIntervalSince1970)

func b64url(_ data: Data) -> String {
    data.base64EncodedString()
        .replacingOccurrences(of: "+", with: "-")
        .replacingOccurrences(of: "/", with: "_")
        .replacingOccurrences(of: "=", with: "")
}

let header = try JSONSerialization.data(withJSONObject: ["alg": "ES256", "kid": args[2]], options: [.sortedKeys])
let claims = try JSONSerialization.data(
    withJSONObject: ["iss": args[3], "iat": now, "exp": now + Int(days * 86400)], options: [.sortedKeys])
let signingInput = "\(b64url(header)).\(b64url(claims))"
let signature = try key.signature(for: Data(signingInput.utf8))
print("\(signingInput).\(b64url(signature.rawRepresentation))")
