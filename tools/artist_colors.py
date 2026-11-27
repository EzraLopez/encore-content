#!/usr/bin/env python3
"""Extract show-card colors from artist portraits, the same rule as
tools/artist_colors.swift (read its header for the rule; keep the two in step).
This one runs where AppKit doesn't (the cloud routines) and needs Pillow
(`python3 -m pip install Pillow`).

    python3 tools/artist_colors.py --only "John Summit" "Cassian" > /tmp/encore-colors.json
    python3 tools/apply_artist_colors.py --no-copy /tmp/encore-colors.json

Output: {"Artist": {"color": "#RRGGBB", "color2": "#RRGGBB"}, ...}
"""

import argparse
import colorsys
from functools import lru_cache
from io import BytesIO
import json
from pathlib import Path
from urllib.request import urlopen

CONFIG = Path(__file__).resolve().parent.parent / "v2" / "config.json"
SIDE = 48
K = 6


def hsl(c):
    """(r, g, b) in 0..1 -> (hue degrees, saturation, lightness)."""
    h, l, s = colorsys.rgb_to_hls(*c)
    return h * 360, s, l


def from_hsl(h, s, l):
    return colorsys.hls_to_rgb((h % 360) / 360, l, s)


def chroma(c):
    _, s, l = hsl(c)
    return s * (1 - abs(2 * l - 1))


def luminance(c):
    def linear(v):
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (linear(v) for v in c)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_with_white(c):
    return 1.05 / (luminance(c) + 0.05)


def scaled(c, f):
    return tuple(v * f for v in c)


def hex_color(c):
    return "#" + "".join(f"{int(round(min(max(v, 0), 1) * 255)):02X}" for v in c)


def for_white_text(c, sat_floor, sat_cap):
    """Lightness lifted into [0.32, 0.5], saturation held in [floor, cap], then
    darkened until white text holds 4.6:1."""
    h, s, l = hsl(c)
    s = min(max(s, sat_floor), sat_cap)
    l = min(max(l, 0.32), 0.5)
    out = from_hsl(h, s, l)
    while contrast_with_white(out) < 4.6 and l > 0.05:
        l -= 0.01
        out = from_hsl(h, s, l)
    return out


def card_colors(pixels):
    """pixels: list of (r, g, b) in 0..1 -> (top, bottom)."""
    n = len(pixels)
    centers = [pixels[(j * n) // K + n // (2 * K)] for j in range(K)]
    assign = [0] * n
    for _ in range(12):
        for i, p in enumerate(pixels):
            best, best_d = 0, float("inf")
            for j, c in enumerate(centers):
                d = (p[0] - c[0]) ** 2 + (p[1] - c[1]) ** 2 + (p[2] - c[2]) ** 2
                if d < best_d:
                    best, best_d = j, d
            assign[i] = best
        for j in range(K):
            members = [pixels[i] for i in range(n) if assign[i] == j]
            if members:
                m = len(members)
                centers[j] = tuple(sum(p[ch] for p in members) / m for ch in range(3))
    share = [assign.count(j) / n for j in range(K)]

    def score(j):
        h, s, l = hsl(centers[j])
        c = s * (1 - abs(2 * l - 1))
        if 5 <= h <= 45 and s < 0.75:
            c *= 0.25
        if l > 0.85 or l < 0.08:
            c *= 0.2
        return share[j] ** 0.6 * c

    ranked = sorted(range(K), key=lambda j: (-score(j), j))
    first = ranked[0]
    if not (chroma(centers[first]) > 0.05 and share[first] > 0.03):
        by_size = sorted(range(K), key=lambda j: (-share[j], j))
        darkest = min(by_size[:3], key=lambda j: luminance(centers[j]))
        h, _, _ = hsl(centers[darkest])
        return from_hsl(h, 0.08, 0.24), from_hsl(h, 0.06, 0.12)
    top = for_white_text(centers[first], 0.35, 0.85)
    h1, _, _ = hsl(centers[first])
    other = None
    for j in ranked[1:]:
        h, _, _ = hsl(centers[j])
        dh = min(abs(h - h1), 360 - abs(h - h1))
        if dh > 25 and chroma(centers[j]) > 0.06 and share[j] > 0.04:
            other = j
            break
    bottom = scaled(for_white_text(centers[other], 0.3, 0.8), 0.82) if other is not None else scaled(top, 0.62)
    return top, bottom


@lru_cache(maxsize=None)
def portrait_colors(url):
    from PIL import Image, ImageOps

    with urlopen(url, timeout=15) as response:
        data = response.read()
    with Image.open(BytesIO(data)) as source:
        image = ImageOps.exif_transpose(source).convert("RGBA")
        backdrop = Image.new("RGBA", image.size, (0, 0, 0, 255))
        backdrop.alpha_composite(image)
        small = backdrop.convert("RGB").resize((SIDE, SIDE), Image.Resampling.BILINEAR)
        raw = small.tobytes()
    pixels = [tuple(raw[i + ch] / 255 for ch in range(3)) for i in range(0, len(raw), 3)]
    top, bottom = card_colors(pixels)
    return {"color": hex_color(top), "color2": hex_color(bottom)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", nargs="+", required=True, metavar="ARTIST")
    args = parser.parse_args()
    artists = json.loads(CONFIG.read_text(encoding="utf-8"))["artists"]
    colors = {name: portrait_colors(artists[name]["imageUrl"]) for name in args.only if artists.get(name, {}).get("imageUrl")}
    print(json.dumps(colors, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
