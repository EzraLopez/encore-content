#!/usr/bin/env python3
"""Enrich v2/config.json with per-artist data (the top-level `artists`
object): real Apple Music artist-page URLs and festival profile
photos.

Sources, both keyless:
  * Apple Music URLs — the iTunes Search API
    (entity=musicArtist). The returned artistLinkUrl is a real
    artist page; linking the /us/search?term= page instead is a
    dead end inside the Music app, which is why this exists.
  * Photos — Seismic Dance Event's official lineup page publishes
    a `*-PROFILE-SDE9` portrait per artist (600x600 variant used).

Matching is conservative: a result is only accepted when the
normalized names agree (accents/case/punctuation stripped), so a
wrong artist is never linked. For "A b2b B" billings the
first-billed artist supplies both fields. Re-runnable: existing
entries are kept unless --force is passed.

Usage: python3 tools/enrich_artists.py [--force]
"""

import json
import re
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "v2" / "config.json"
SEISMIC_LINEUP_URL = "https://www.seismicdanceevent.com/lineup"
UA = {"User-Agent": "Mozilla/5.0 (Encore catalog enrichment)"}


def norm(name: str) -> str:
    decomposed = unicodedata.normalize("NFKD", name)
    ascii_only = "".join(c for c in decomposed if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]", "", ascii_only.lower())


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.read()


def seismic_image_slugs() -> dict:
    """slug -> 600x600 profile image URL, from the lineup page."""
    html = fetch(SEISMIC_LINEUP_URL).decode("utf-8", "ignore")
    urls = set(re.findall(
        r"https://www\.seismicdanceevent\.com/wp-content/uploads/[^\"'\s]*-PROFILE-SDE9(?:-\d+x\d+)?\.png",
        html))
    slugs = {}
    for url in urls:
        base = url.rsplit("/", 1)[-1]
        slug = re.sub(r"-PROFILE-SDE9.*$", "", base)
        # Prefer the 600x600 variant for every slug.
        slugs[norm(slug)] = re.sub(r"(-\d+x\d+)?\.png$", "-600x600.png", url)
    return slugs


_cache: dict = {}


def itunes_artist_url(candidate: str):
    """The Apple Music artist page URL for `candidate`, or None."""
    key = norm(candidate)
    if key in _cache:
        return _cache[key]
    url = None
    try:
        query = urllib.parse.urlencode(
            {"term": candidate, "entity": "musicArtist", "limit": 5, "country": "US"})
        data = json.loads(fetch(f"https://itunes.apple.com/search?{query}"))
        for result in data.get("results", []):
            name = result.get("artistName", "")
            if norm(name) == key or (
                len(key) >= 3 and (key in norm(name) or norm(name) in key)
            ):
                link = result.get("artistLinkUrl", "")
                url = link.split("?")[0] if link else None
                break
    except Exception as exc:  # network hiccup: leave unmatched
        print(f"  ! lookup failed for {candidate!r}: {exc}", file=sys.stderr)
    _cache[key] = url
    time.sleep(0.12)
    return url


def candidates(billing: str):
    parts = re.split(r"\s+b2b\s+", billing, flags=re.IGNORECASE)
    seen, out = set(), []
    for part in [billing, *parts]:
        part = part.strip()
        if part and norm(part) not in seen:
            seen.add(norm(part))
            out.append(part)
    return out


def main() -> int:
    force = "--force" in sys.argv
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    existing = {} if force else dict(config.get("artists", {}))

    billings = sorted({
        s["artist"]
        for fest in config["festivals"]
        for day in fest.get("days", [])
        for stage in day.get("stages", [])
        for s in stage.get("sets", [])
    })
    print(f"{len(billings)} unique billings")

    slugs = seismic_image_slugs()
    print(f"{len(slugs)} Seismic profile images")

    artists = dict(existing)
    stats = {"am": 0, "img": 0, "both": 0, "none": 0}
    for billing in billings:
        if billing in artists:
            continue
        entry = {}
        for cand in candidates(billing):
            if "appleMusicUrl" not in entry:
                found = itunes_artist_url(cand)
                if found:
                    entry["appleMusicUrl"] = found
            if "imageUrl" not in entry and norm(cand) in slugs:
                entry["imageUrl"] = slugs[norm(cand)]
            if len(entry) == 2:
                break
        if entry:
            artists[billing] = entry
        if "appleMusicUrl" in entry:
            stats["am"] += 1
        if "imageUrl" in entry:
            stats["img"] += 1
        if len(entry) == 2:
            stats["both"] += 1
        if not entry:
            stats["none"] += 1

    config["artists"] = dict(sorted(artists.items()))
    from datetime import datetime, timezone
    config["meta"]["version"] = int(config["meta"].get("version", 1)) + 1
    config["meta"]["publishedAt"] = (
        datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    CONFIG.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n",
                      encoding="utf-8")
    print(f"artists entries: {len(artists)} "
          f"(appleMusic {stats['am']}, images {stats['img']}, "
          f"both {stats['both']}, unmatched-new {stats['none']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
