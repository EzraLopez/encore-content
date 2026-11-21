// artist_colors.swift: give each artist with a photo a colour of their own
// (Ezra, Nov 21, 2026: show cards should "use colors that match the artists").
// Reads v2/config.json, downloads each artist's imageUrl, finds the photo's
// most vivid hue (pixels weighted by chroma, in 10° bins), and writes
// `color` as "#RRGGBB" at HSL(hue, 62%, 52%) — the same saturation and
// lightness as a festival's generated accent, so the apps' card shading keeps
// white text readable. A black-and-white photo gets no colour (the apps then
// use one from the name). Existing colours are kept unless --force.
//
//   swift tools/artist_colors.swift [--force] [--limit N] > /tmp/colours.json
//   python3 tools/apply_artist_colors.py /tmp/colours.json
import AppKit
import Foundation

let args = CommandLine.arguments
let force = args.contains("--force")
let limit = args.firstIndex(of: "--limit").flatMap { Int(args[$0 + 1]) } ?? .max
let path = "v2/config.json"
let data = try Data(contentsOf: URL(fileURLWithPath: path))
let root = try JSONSerialization.jsonObject(with: data) as! [String: Any]
let artists = root["artists"] as? [String: [String: Any]] ?? [:]

func hsl(_ r: Double, _ g: Double, _ b: Double) -> (h: Double, s: Double, l: Double) {
    let mx = max(r, g, b), mn = min(r, g, b), l = (mx + mn) / 2
    guard mx != mn else { return (0, 0, l) }
    let d = mx - mn
    let s = l > 0.5 ? d / (2 - mx - mn) : d / (mx + mn)
    var h: Double
    switch mx {
    case r: h = (g - b) / d + (g < b ? 6 : 0)
    case g: h = (b - r) / d + 2
    default: h = (r - g) / d + 4
    }
    return (h * 60, s, l)
}

func hex(hue: Double, s: Double = 0.62, l: Double = 0.52) -> String {
    let c = (1 - abs(2 * l - 1)) * s
    let x = c * (1 - abs((hue / 60).truncatingRemainder(dividingBy: 2) - 1))
    let m = l - c / 2
    let (r1, g1, b1): (Double, Double, Double)
    switch hue {
    case ..<60: (r1, g1, b1) = (c, x, 0)
    case ..<120: (r1, g1, b1) = (x, c, 0)
    case ..<180: (r1, g1, b1) = (0, c, x)
    case ..<240: (r1, g1, b1) = (0, x, c)
    case ..<300: (r1, g1, b1) = (x, 0, c)
    default: (r1, g1, b1) = (c, 0, x)
    }
    return String(format: "#%02X%02X%02X", Int(((r1 + m) * 255).rounded()), Int(((g1 + m) * 255).rounded()), Int(((b1 + m) * 255).rounded()))
}

/// The photo's most vivid hue, or nil when it has hardly any colour.
func vividHue(_ url: URL) -> Double? {
    guard let data = try? Data(contentsOf: url), let image = NSImage(data: data),
          let cg = image.cgImage(forProposedRect: nil, context: nil, hints: nil) else { return nil }
    let side = 48
    var pixels = [UInt8](repeating: 0, count: side * side * 4)
    guard let ctx = CGContext(data: &pixels, width: side, height: side, bitsPerComponent: 8, bytesPerRow: side * 4,
                              space: CGColorSpaceCreateDeviceRGB(), bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue) else { return nil }
    ctx.draw(cg, in: CGRect(x: 0, y: 0, width: side, height: side))
    var bins = [Double](repeating: 0, count: 36)
    var hueSum = [Double](repeating: 0, count: 36)
    var total = 0.0
    for i in stride(from: 0, to: pixels.count, by: 4) {
        let (h, s, l) = hsl(Double(pixels[i]) / 255, Double(pixels[i + 1]) / 255, Double(pixels[i + 2]) / 255)
        var weight = s * (1 - abs(2 * l - 1))   // chroma: vivid, not near black or white
        guard weight > 0.12 else { continue }
        // Faces are most of a portrait: skin hues (about 5°-45°, not
        // strongly saturated) count for little, so a jacket, a light or
        // a backdrop sets the colour.
        if h >= 5 && h <= 45 && s < 0.75 { weight *= 0.15 }
        let bin = Int(h / 10) % 36
        bins[bin] += weight
        hueSum[bin] += h * weight
        total += weight
    }
    // Hardly any colour: a black-and-white portrait.
    guard total > Double(side * side) * 0.03, let best = bins.indices.max(by: { bins[$0] < bins[$1] }) else { return nil }
    return hueSum[best] / bins[best]
}

var done = 0, coloured = 0, grey = 0
var colours: [String: String?] = [:]
let only = args.firstIndex(of: "--only").map { Set(args[($0 + 1)...].prefix { !$0.hasPrefix("--") }) }
for name in artists.keys.sorted() where done < limit && (only?.contains(name) ?? true) {
    guard let info = artists[name], let raw = info["imageUrl"] as? String, let url = URL(string: raw) else { continue }
    if info["color"] != nil && !force { continue }
    done += 1
    if let hue = vividHue(url) {
        colours[name] = hex(hue: hue)
        coloured += 1
    } else {
        colours[name] = .some(nil)
        grey += 1
    }
}
// The catalog keeps its own formatting: print the colours, and
// tools/apply_artist_colors.py writes them in.
let out = try JSONSerialization.data(withJSONObject: colours.mapValues { $0 ?? NSNull() as Any }, options: [.sortedKeys])
FileHandle.standardOutput.write(out)
FileHandle.standardError.write("looked at \(done): \(coloured) coloured, \(grey) black and white\n".data(using: .utf8)!)
