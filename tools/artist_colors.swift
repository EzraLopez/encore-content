// artist_colors.swift: give each artist with a photo the two colours of their
// show cards (Ezra, Nov 21, 2026: show cards should "use colors that match the
// artists"; Nov 26, 2026: "we should look into improving our color matching
// algorithms for cards", and he chose this rule from mocks,
// https://claude.ai/artifact/4sGUgPC8o6rTqFj7vwpp7B).
//
// The rule (tools/artist_colors.py is the same rule in Python, for machines
// without AppKit; keep the two in step):
// 1. The photo at 48 x 48 is grouped into 6 colours (k-means, 12 rounds,
//    starting from evenly spaced pixels).
// 2. Each group's score is share^0.6 x chroma, with skin (hue 5-45 degrees,
//    saturation under 0.75) at a quarter and paper white or deep shadow
//    (lightness over 0.85 or under 0.08) at a fifth.
// 3. The best group with chroma over 0.05 and over 3% of the photo is the
//    card's top colour (`color`): its own hue, its saturation held between
//    0.35 and 0.85, its lightness lifted to at least 0.32 and at most 0.5,
//    then darkened until white text holds 4.6:1.
// 4. The bottom colour (`color2`): the next telling group at least 25 degrees
//    away in hue (chroma over 0.06, over 4% of the photo), made safe the same
//    way (saturation 0.3-0.8) and scaled by 0.82; else the top scaled by 0.62.
// 5. A photo with no real colour gets a deep neutral leaning the way its
//    darkest large group leans: HSL(h, 8%, 24%) over HSL(h, 6%, 12%).
// Both colours hold 4.6:1 with white, so older apps that read only `color`
// can put white text straight on it.
//
//   swift tools/artist_colors.swift [--force] [--limit N] [--only NAME ...] > /tmp/colours.json
//   python3 tools/apply_artist_colors.py /tmp/colours.json
//
// Output: {"Artist": {"color": "#RRGGBB", "color2": "#RRGGBB"}, ...}. Without
// --force, artists that already have `color2` are skipped (a `color` alone is
// the older rule and is recomputed).
import AppKit
import Foundation

let args = CommandLine.arguments
let force = args.contains("--force")
let limit = args.firstIndex(of: "--limit").flatMap { Int(args[$0 + 1]) } ?? .max
let only = args.firstIndex(of: "--only").map { Set(args[($0 + 1)...].prefix { !$0.hasPrefix("--") }) }
let path = "v2/config.json"
let data = try Data(contentsOf: URL(fileURLWithPath: path))
let root = try JSONSerialization.jsonObject(with: data) as! [String: Any]
let artists = root["artists"] as? [String: [String: Any]] ?? [:]

struct RGB { var r, g, b: Double }

func hsl(_ c: RGB) -> (h: Double, s: Double, l: Double) {
    let mx = max(c.r, c.g, c.b), mn = min(c.r, c.g, c.b), l = (mx + mn) / 2
    guard mx != mn else { return (0, 0, l) }
    let d = mx - mn
    let s = l > 0.5 ? d / (2 - mx - mn) : d / (mx + mn)
    var h: Double
    if mx == c.r { h = (c.g - c.b) / d + (c.g < c.b ? 6 : 0) } else if mx == c.g { h = (c.b - c.r) / d + 2 } else { h = (c.r - c.g) / d + 4 }
    return (h * 60, s, l)
}

func fromHSL(_ h: Double, _ s: Double, _ l: Double) -> RGB {
    let c = (1 - abs(2 * l - 1)) * s, x = c * (1 - abs((h / 60).truncatingRemainder(dividingBy: 2) - 1)), m = l - c / 2
    let (r, g, b): (Double, Double, Double)
    switch h {
    case ..<60: (r, g, b) = (c, x, 0)
    case ..<120: (r, g, b) = (x, c, 0)
    case ..<180: (r, g, b) = (0, c, x)
    case ..<240: (r, g, b) = (0, x, c)
    case ..<300: (r, g, b) = (x, 0, c)
    default: (r, g, b) = (c, 0, x)
    }
    return RGB(r: r + m, g: g + m, b: b + m)
}

func chroma(_ c: RGB) -> Double { let (_, s, l) = hsl(c); return s * (1 - abs(2 * l - 1)) }
func linear(_ v: Double) -> Double { v <= 0.04045 ? v / 12.92 : pow((v + 0.055) / 1.055, 2.4) }
func luminance(_ c: RGB) -> Double { 0.2126 * linear(c.r) + 0.7152 * linear(c.g) + 0.0722 * linear(c.b) }
func contrastWithWhite(_ c: RGB) -> Double { 1.05 / (luminance(c) + 0.05) }
func scaled(_ c: RGB, _ f: Double) -> RGB { RGB(r: c.r * f, g: c.g * f, b: c.b * f) }
func hex(_ c: RGB) -> String {
    func byte(_ v: Double) -> Int { Int((min(max(v, 0), 1) * 255).rounded()) }
    return String(format: "#%02X%02X%02X", byte(c.r), byte(c.g), byte(c.b))
}

func pixels(_ url: URL) -> [RGB]? {
    guard let data = try? Data(contentsOf: url), let image = NSImage(data: data),
          let cg = image.cgImage(forProposedRect: nil, context: nil, hints: nil) else { return nil }
    let side = 48
    var px = [UInt8](repeating: 0, count: side * side * 4)
    guard let ctx = CGContext(data: &px, width: side, height: side, bitsPerComponent: 8, bytesPerRow: side * 4,
                              space: CGColorSpaceCreateDeviceRGB(), bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue) else { return nil }
    // A transparent photo sits on black, as the Python tool composites it.
    ctx.setFillColor(CGColor(red: 0, green: 0, blue: 0, alpha: 1))
    ctx.fill(CGRect(x: 0, y: 0, width: side, height: side))
    ctx.draw(cg, in: CGRect(x: 0, y: 0, width: side, height: side))
    return stride(from: 0, to: px.count, by: 4).map { RGB(r: Double(px[$0]) / 255, g: Double(px[$0 + 1]) / 255, b: Double(px[$0 + 2]) / 255) }
}

/// Lightness lifted into [0.32, 0.5], saturation held in [floor, cap], then
/// darkened until white text holds 4.6:1.
func forWhiteText(_ c: RGB, satFloor: Double, satCap: Double) -> RGB {
    var (h, s, l) = hsl(c)
    s = min(max(s, satFloor), satCap)
    l = min(max(l, 0.32), 0.5)
    var out = fromHSL(h, s, l)
    while contrastWithWhite(out) < 4.6 && l > 0.05 { l -= 0.01; out = fromHSL(h, s, l) }
    return out
}

func cardColours(_ px: [RGB]) -> (top: RGB, bottom: RGB) {
    let k = 6
    var centers = (0..<k).map { px[($0 * px.count) / k + px.count / (2 * k)] }
    var assign = [Int](repeating: 0, count: px.count)
    for _ in 0..<12 {
        for (i, p) in px.enumerated() {
            var best = 0, bestDistance = Double.infinity
            for (j, c) in centers.enumerated() {
                let d = pow(p.r - c.r, 2) + pow(p.g - c.g, 2) + pow(p.b - c.b, 2)
                if d < bestDistance { bestDistance = d; best = j }
            }
            assign[i] = best
        }
        for j in 0..<k {
            let members = px.indices.filter { assign[$0] == j }
            guard !members.isEmpty else { continue }
            let n = Double(members.count)
            centers[j] = RGB(r: members.map { px[$0].r }.reduce(0, +) / n,
                             g: members.map { px[$0].g }.reduce(0, +) / n,
                             b: members.map { px[$0].b }.reduce(0, +) / n)
        }
    }
    let share = (0..<k).map { j in Double(assign.filter { $0 == j }.count) / Double(px.count) }
    func score(_ j: Int) -> Double {
        let (h, s, l) = hsl(centers[j])
        var c = s * (1 - abs(2 * l - 1))
        if h >= 5 && h <= 45 && s < 0.75 { c *= 0.25 }
        if l > 0.85 || l < 0.08 { c *= 0.2 }
        return pow(share[j], 0.6) * c
    }
    let ranked = (0..<k).sorted { score($0) != score($1) ? score($0) > score($1) : $0 < $1 }
    let first = ranked[0]
    guard chroma(centers[first]) > 0.05 && share[first] > 0.03 else {
        let bySize = (0..<k).sorted { share[$0] != share[$1] ? share[$0] > share[$1] : $0 < $1 }
        let darkest = bySize.prefix(3).min { luminance(centers[$0]) < luminance(centers[$1]) } ?? bySize[0]
        let (h, _, _) = hsl(centers[darkest])
        return (fromHSL(h, 0.08, 0.24), fromHSL(h, 0.06, 0.12))
    }
    let top = forWhiteText(centers[first], satFloor: 0.35, satCap: 0.85)
    let (h1, _, _) = hsl(centers[first])
    let other = ranked.dropFirst().first { j in
        let (h, _, _) = hsl(centers[j])
        let dh = min(abs(h - h1), 360 - abs(h - h1))
        return dh > 25 && chroma(centers[j]) > 0.06 && share[j] > 0.04
    }
    let bottom = other.map { scaled(forWhiteText(centers[$0], satFloor: 0.3, satCap: 0.8), 0.82) } ?? scaled(top, 0.62)
    return (top, bottom)
}

var done = 0
var colours: [String: Any] = [:]
for name in artists.keys.sorted() where done < limit && (only?.contains(name) ?? true) {
    guard let info = artists[name], let raw = info["imageUrl"] as? String, let url = URL(string: raw) else { continue }
    if info["color2"] != nil && !force && only == nil { continue }
    guard let px = pixels(url) else {
        FileHandle.standardError.write("could not read the photo for \(name)\n".data(using: .utf8)!)
        continue
    }
    done += 1
    let (top, bottom) = cardColours(px)
    colours[name] = ["color": hex(top), "color2": hex(bottom)]
}
// The catalog keeps its own formatting: print the colours, and
// tools/apply_artist_colors.py writes them in.
let out = try JSONSerialization.data(withJSONObject: colours, options: [.sortedKeys, .prettyPrinted])
FileHandle.standardOutput.write(out)
FileHandle.standardError.write("looked at \(done)\n".data(using: .utf8)!)
