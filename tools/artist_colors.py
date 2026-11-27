#!/usr/bin/env python3
"""Extract card colors from portraits using the same hue rules as artist_colors.swift."""

import argparse
import colorsys
from functools import lru_cache
from io import BytesIO
import json
from pathlib import Path
from urllib.request import urlopen

CONFIG = Path(__file__).resolve().parent.parent / "v2" / "config.json"
SIDE = 48


def color_from_pixels(pixels):
    weights = [0.0] * 36
    hues = [0.0] * 36
    for red, green, blue in pixels:
        hue, lightness, saturation = colorsys.rgb_to_hls(red / 255, green / 255, blue / 255)
        hue *= 360
        weight = saturation * (1 - abs(2 * lightness - 1))
        if weight <= 0.12:
            continue
        if 5 <= hue <= 45 and saturation < 0.75:
            weight *= 0.15
        bucket = int(hue / 10) % 36
        weights[bucket] += weight
        hues[bucket] += hue * weight
    if sum(weights) <= SIDE * SIDE * 0.03:
        return None
    best = max(range(36), key=weights.__getitem__)
    rgb = colorsys.hls_to_rgb(hues[best] / weights[best] / 360, 0.52, 0.62)
    return "#" + "".join(f"{int(channel * 255 + 0.5):02X}" for channel in rgb)


@lru_cache(maxsize=None)
def portrait_color(url):
    from PIL import Image, ImageOps

    with urlopen(url, timeout=15) as response:
        data = response.read()
    with Image.open(BytesIO(data)) as source:
        image = ImageOps.exif_transpose(source).convert("RGBA")
        backdrop = Image.new("RGBA", image.size, (0, 0, 0, 255))
        backdrop.alpha_composite(image)
        pixels = backdrop.convert("RGB").resize((SIDE, SIDE), Image.Resampling.BILINEAR)
        rgb = pixels.tobytes()
        return color_from_pixels(rgb[index:index + 3] for index in range(0, len(rgb), 3))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", nargs="+", required=True, metavar="ARTIST")
    args = parser.parse_args()
    artists = json.loads(CONFIG.read_text(encoding="utf-8"))["artists"]
    colors = {name: portrait_color(artists[name]["imageUrl"]) for name in args.only}
    print(json.dumps(colors, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
