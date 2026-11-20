#!/usr/bin/env python3
"""Fills in latitude / longitude for festivals that have none (Nov 19, 2026).

The profile's Map tab places festivals by the catalog's coordinates; one
without them is left off the map. This looks each missing one up by its
`location` ("Olympic Valley, CA") with Open-Meteo's free geocoder (no key,
works in the cloud routines too), picks the result whose region or country
matches the part after the comma, and writes it back. It never changes a
festival that already has coordinates.

  python3 tools/add_coordinates.py            # show what it would add
  python3 tools/add_coordinates.py --write    # add them (then run the validator)
  ... --write --keep-version                  # add them without bumping meta.version

Check new pins on a map before publishing: a common town name can match the
wrong place. tools/geocode.swift (Apple's geocoder, by venue) is more
precise on a Mac.
"""
import argparse
import datetime
import json
import sys
import time
import urllib.parse
import urllib.request

CONFIG = "v2/config.json"
US = {"AL":"Alabama","AK":"Alaska","AZ":"Arizona","AR":"Arkansas","CA":"California","CO":"Colorado","CT":"Connecticut",
      "DE":"Delaware","DC":"District of Columbia","FL":"Florida","GA":"Georgia","HI":"Hawaii","ID":"Idaho","IL":"Illinois",
      "IN":"Indiana","IA":"Iowa","KS":"Kansas","KY":"Kentucky","LA":"Louisiana","ME":"Maine","MD":"Maryland",
      "MA":"Massachusetts","MI":"Michigan","MN":"Minnesota","MS":"Mississippi","MO":"Missouri","MT":"Montana",
      "NE":"Nebraska","NV":"Nevada","NH":"New Hampshire","NJ":"New Jersey","NM":"New Mexico","NY":"New York",
      "NC":"North Carolina","ND":"North Dakota","OH":"Ohio","OK":"Oklahoma","OR":"Oregon","PA":"Pennsylvania",
      "RI":"Rhode Island","SC":"South Carolina","SD":"South Dakota","TN":"Tennessee","TX":"Texas","UT":"Utah",
      "VT":"Vermont","VA":"Virginia","WA":"Washington","WV":"West Virginia","WI":"Wisconsin","WY":"Wyoming"}


ALIASES = {"uk": "gb", "u.k.": "gb", "england": "gb", "scotland": "gb", "wales": "gb", "usa": "us", "u.s.": "us"}


def lookup(location):
    parts = [p.strip() for p in location.split(",") if p.strip()]
    if not parts:
        return None
    hints = [US.get(p.upper(), ALIASES.get(p.lower(), p)).lower() for p in parts[1:]]
    q = urllib.parse.urlencode({"name": parts[0], "count": 10, "language": "en", "format": "json"})
    with urllib.request.urlopen(f"https://geocoding-api.open-meteo.com/v1/search?{q}", timeout=20) as r:
        results = json.load(r).get("results") or []
    def fits(x):
        if not hints:
            return True
        names = [str(x.get(k, "")).lower() for k in ("admin1", "admin2", "country", "country_code")]
        return any(h == n or (len(h) > 3 and h in n) for h in hints for n in names)
    best = next((x for x in results if fits(x)), None)
    return (round(best["latitude"], 4), round(best["longitude"], 4)) if best else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--keep-version", action="store_true",
                    help="leave meta.version and publishedAt alone (for routines that bump them once per branch)")
    args = ap.parse_args()
    raw = open(CONFIG, encoding="utf-8").read()
    c = json.loads(raw)
    assert json.dumps(c, indent=2, ensure_ascii=False) + "\n" == raw, "config.json isn't in canonical form"
    added, missed = 0, []
    for f in c["festivals"]:
        if "latitude" in f and "longitude" in f:
            continue
        found = lookup(f.get("location", ""))
        time.sleep(0.3)
        if not found:
            missed.append(f["id"])
            continue
        print(f"{f['id']}: {found[0]}, {found[1]}  ({f.get('location')})")
        added += 1
        if args.write:
            out = {}
            anchor = "venue" if "venue" in f else "location"
            for k, v in f.items():
                out[k] = v
                if k == anchor:
                    out["latitude"], out["longitude"] = found
            f.clear(); f.update(out)
    for m in missed:
        print(f"{m}: nothing found; add latitude/longitude by hand", file=sys.stderr)
    if args.write and added:
        if not args.keep_version:
            c["meta"]["version"] += 1
            c["meta"]["publishedAt"] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        open(CONFIG, "w", encoding="utf-8").write(json.dumps(c, indent=2, ensure_ascii=False) + "\n")
    print(f"{added} added{' (not written: pass --write)' if added and not args.write else ''}, {len(missed)} not found")


if __name__ == "__main__":
    main()
