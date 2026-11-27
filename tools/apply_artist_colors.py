#!/usr/bin/env python3
"""Write the colours tools/artist_colors.swift found into v2/config.json's
`artists` (`color`: "#RRGGBB"; null drops it), keeping the catalog's format.

    swift tools/artist_colors.swift > /tmp/colours.json
    python3 tools/apply_artist_colors.py /tmp/colours.json
"""
import argparse
import json
from pathlib import Path

CONFIG = Path(__file__).resolve().parent.parent / "v2" / "config.json"
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("colors", nargs="?", type=Path)
parser.add_argument("--no-copy", action="store_true", help="Only apply colors to the supplied artist names")
args = parser.parse_args()
colours = json.loads(args.colors.read_text()) if args.colors else {}
config = json.loads(CONFIG.read_text(encoding="utf-8"))
artists = config.get("artists", {})
changed = 0
for name, colour in colours.items():
    info = artists.get(name)
    if info is None:
        continue
    if colour is None:
        if info.pop("color", None) is not None:
            changed += 1
    elif info.get("color") != colour:
        info["color"] = colour
        changed += 1

# One artist under several spellings ("IT'S MURPH", "it's murph", "it’s murph";
# Nov 21, 2026): a spelling without the photo or colour takes them from one
# with them, when the names' letters are the same.
def letters(name):
    return "".join(ch for ch in name.casefold() if ch.isalnum())

filled = 0
if not args.no_copy:
    best = {}
    for name in sorted(artists):
        info = artists[name]
        if info.get("imageUrl"):
            best.setdefault(letters(name), info)
    for name, info in artists.items():
        donor = best.get(letters(name))
        if not donor or donor is info:
            continue
        for field in ("imageUrl", "color"):
            if not info.get(field) and donor.get(field):
                info[field] = donor[field]
                filled += 1

CONFIG.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print(f"artist colours changed: {changed}; filled from other spellings: {filled}")
