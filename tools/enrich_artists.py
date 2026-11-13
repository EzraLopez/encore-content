#!/usr/bin/env python3
"""Enrich v2/config.json with per-artist data (the top-level `artists`
object): real Apple Music and Spotify artist-page URLs and festival
profile photos.

Sources, all keyless:
  * Spotify URLs (Nov 13, 2026) — Wikidata's "Spotify artist ID"
    (P1902), looked up by the artist's exact label or alias. Only an
    unambiguous match is taken (one Spotify id across every item with
    that name); the apps fall back to a Spotify search otherwise.
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


WIKIDATA_SPARQL = "https://query.wikidata.org/sparql"


def wikidata_spotify_ids(names):
    """{normalized name: Spotify artist id} for names Wikidata knows
    unambiguously. Exact label/alias match (case as written, English or
    no language), batched; a name whose items carry more than one
    Spotify id is skipped rather than guessed."""
    found = {}
    names = sorted(set(names))
    for i in range(0, len(names), 40):
        batch = names[i:i + 40]
        values = " ".join(
            '"%s"@en' % n.replace("\\", "\\\\").replace('"', '\\"') for n in batch
        )
        query = (
            "SELECT ?name ?spotify WHERE { VALUES ?name { %s } "
            "{ ?item rdfs:label ?name } UNION { ?item skos:altLabel ?name } "
            "?item wdt:P1902 ?spotify . }" % values
        )
        url = WIKIDATA_SPARQL + "?" + urllib.parse.urlencode({"query": query, "format": "json"})
        try:
            data = json.loads(fetch(url))
        except Exception as exc:  # noqa: BLE001 - best effort per batch
            print(f"  wikidata batch {i // 40} failed: {exc}")
            continue
        ids = {}
        for row in data["results"]["bindings"]:
            ids.setdefault(norm(row["name"]["value"]), set()).add(row["spotify"]["value"])
        for key, values_found in ids.items():
            if len(values_found) == 1:
                found[key] = next(iter(values_found))
        time.sleep(1)
    return found


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
    } | {
        # Announced artists without set times count too.
        entry["artist"]
        for fest in config["festivals"]
        for entry in fest.get("lineup", [])
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

    # Spotify, for every billing still without one (existing entries too).
    want = {b: candidates(b) for b in billings if "spotifyUrl" not in artists.get(b, {})}
    spotify = wikidata_spotify_ids([c for cands in want.values() for c in cands])
    added_spotify = 0
    for billing, cands in want.items():
        sid = next((spotify[norm(c)] for c in cands if norm(c) in spotify), None)
        if sid:
            artists.setdefault(billing, {})["spotifyUrl"] = f"https://open.spotify.com/artist/{sid}"
            added_spotify += 1
    print(f"spotify: {added_spotify} of {len(want)} billings matched on Wikidata")

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
