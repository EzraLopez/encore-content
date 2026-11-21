#!/usr/bin/env python3
"""Write the colours tools/artist_colors.swift found into v2/config.json's
`artists` (`color`: "#RRGGBB"; null drops it), keeping the catalog's format.

    swift tools/artist_colors.swift > /tmp/colours.json
    python3 tools/apply_artist_colors.py /tmp/colours.json
"""
import json
import sys
from pathlib import Path

CONFIG = Path(__file__).resolve().parent.parent / "v2" / "config.json"
colours = json.loads(Path(sys.argv[1]).read_text())
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
CONFIG.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print(f"artist colours changed: {changed}")
