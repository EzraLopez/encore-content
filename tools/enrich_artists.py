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
  * Photos (Nov 13, 2026) — Apple Music artist artwork from the
    MusicKit catalog API (api.music.apple.com), for every artist with
    an Apple Music link and no photo yet. This one needs a MusicKit
    developer token: set APPLE_MUSIC_TOKEN locally, or run where a
    network secret injects it for api.music.apple.com (the cloud
    routine's environment). Without either the pass is skipped. The
    token is never written anywhere by this script.

Matching is conservative: a result is only accepted when the
names agree (accents/case/punctuation stripped, and set labels such
as "(DJ Set)", "Live" or a leading "The" ignored); a name that only
contains the other is never taken, so a wrong artist is not linked.
For "A b2b B" billings the first-billed artist supplies both fields. Re-runnable: existing
entries are kept unless --force is passed.

Usage: python3 tools/enrich_artists.py [--force]
(token: APPLE_MUSIC_TOKEN=$(swift tools/musickit_token.swift <AuthKey.p8> <keyId> <teamId>))
"""

import json
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "v2" / "config.json"
# Names the iTunes search answered with no matching artist, with the date
# of that answer: they are not searched again for MISS_DAYS, so a run only
# pays for new names instead of re-searching every past miss.
MISSES = ROOT / "tools" / "enrich_misses.json"
MISS_DAYS = 30
# Save the config every this many billings, so a run that is stopped
# keeps what it found.
SAVE_EVERY = 25
# This many lookups failing in a row (HTTP 403, no network) means the
# search is refusing this machine: stop searching instead of spending an
# hour on 3-second waits that find nothing.
MAX_FAILS_IN_A_ROW = 10
SEISMIC_LINEUP_URL = "https://www.seismicdanceevent.com/lineup"
UA = {"User-Agent": "Mozilla/5.0 (Encore catalog enrichment)"}


# Letters NFKD does not split into a base letter and an accent.
_FOLD = str.maketrans({"ł": "l", "Ł": "L", "ø": "o", "Ø": "O", "đ": "d", "Đ": "D"})


def norm(name: str) -> str:
    decomposed = unicodedata.normalize("NFKD", name.translate(_FOLD))
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


def bare(name: str) -> str:
    """The name without what a festival adds to it: a set label in
    brackets ("(DJ Set)"), a trailing "Live", "presents ..." and a
    leading "The"."""
    name = re.sub(
        r"\s*(?:\((?:dj set|live|live set|island set)\)|"
        r"\[(?:dj set|live|live set|island set)\])$",
        "", name.strip(), flags=re.IGNORECASE,
    )
    name = re.split(r"\s+(?:presents|pres\.)\s+", name, flags=re.IGNORECASE)[0]
    name = re.sub(r"\s+live$", "", name.strip(), flags=re.IGNORECASE)
    name = re.sub(r"^the\s+", "", name.strip(), flags=re.IGNORECASE)
    return norm(name)


def same_artist(found: str, wanted: str) -> bool:
    """Whether the search result `found` is the billed artist `wanted`.
    The names must be the same, apart from case, accents, punctuation
    and the labels bare() removes. A name that only contains the other
    ("Jackson" / "Michael Jackson", "Malóne" / "Post Malone") is
    another artist, and the apps' search fallback is better than a
    wrong link."""
    if not norm(wanted):  # no letters or digits ("@"): only the same text
        return found.strip().casefold() == wanted.strip().casefold()
    return norm(found) == norm(wanted) or (
        bool(bare(found)) and bare(found) == bare(wanted))


_cache: dict = {}
_fails = {"in_a_row": 0}


class LookupBlocked(Exception):
    """The iTunes search keeps failing: give up on it for this run."""


def lookup_key(candidate: str) -> str:
    return norm(candidate) or candidate.strip().casefold()


def itunes_artist_url(candidate: str):
    """The Apple Music artist page URL for `candidate`, or None."""
    key = lookup_key(candidate)
    if key in _cache:
        return _cache[key]
    url = None
    try:
        query = urllib.parse.urlencode(
            {"term": candidate, "entity": "musicArtist", "limit": 5, "country": "US"})
        data = json.loads(fetch(f"https://itunes.apple.com/search?{query}"))
        for result in data.get("results", []):
            # The search also returns Apple Books authors and old iTunes
            # pages under the same name: only an Apple Music artist page
            # is the musician (the validator refuses anything else).
            link = (result.get("artistLinkUrl") or "").split("?")[0]
            if not link.startswith("https://music.apple.com/"):
                continue
            name = result.get("artistName", "")
            if same_artist(name, candidate):
                url = link
                break
    except Exception as exc:  # network hiccup: leave unmatched, retry next run
        print(f"  ! lookup failed for {candidate!r}: {exc}", file=sys.stderr)
        _fails["in_a_row"] += 1
        if ((isinstance(exc, urllib.error.HTTPError) and exc.code == 429)
                or _fails["in_a_row"] >= MAX_FAILS_IN_A_ROW):
            raise LookupBlocked(str(exc)) from exc
        time.sleep(3.1)
        return None
    _fails["in_a_row"] = 0
    _cache[key] = url
    time.sleep(3.1)
    return url


def candidates(billing: str):
    parts = re.split(r"\s+b2b\s+", billing, maxsplit=1, flags=re.IGNORECASE)
    seen, out = set(), []
    for part in (billing, parts[0]):
        part = part.strip()
        if part and lookup_key(part) not in seen:
            seen.add(lookup_key(part))
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


APPLE_MUSIC_API = "https://api.music.apple.com/v1/catalog/us/artists"
ARTWORK_SIZE = 600


def apple_music_artist_id(url: str):
    """The numeric artist id at the end of an Apple Music artist URL."""
    match = re.search(r"/artist/[^/]+/(\d+)", url) or re.search(r"/artist/(\d+)", url)
    return match.group(1) if match else None


def apple_music_artwork(ids):
    """artist id -> 600x600 artwork URL, from the MusicKit catalog API.
    Returns {} when no token is available (no env var and no proxy)."""
    import os
    token = os.environ.get("APPLE_MUSIC_TOKEN")
    found = {}
    ids = sorted(set(ids))
    for i in range(0, len(ids), 25):
        batch = ids[i:i + 25]
        headers = dict(UA)
        if token:
            headers["Authorization"] = f"Bearer {token}"
        req = urllib.request.Request(f"{APPLE_MUSIC_API}?ids={','.join(batch)}", headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                print("apple music: no developer token (APPLE_MUSIC_TOKEN or a network secret); skipping photos")
                return {}
            print(f"  apple music batch {i // 25} failed: {exc}")
            continue
        except Exception as exc:  # noqa: BLE001 - network hiccup: next batch
            print(f"  apple music batch {i // 25} failed: {exc}")
            continue
        for item in data.get("data", []):
            art = item.get("attributes", {}).get("artwork", {})
            template = art.get("url")
            if template:
                found[item["id"]] = (template.replace("{w}", str(ARTWORK_SIZE))
                                     .replace("{h}", str(ARTWORK_SIZE)).replace("{f}", "jpg"))
        time.sleep(0.3)
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
    from datetime import date, timedelta
    today = date.today().isoformat()
    cutoff = (date.today() - timedelta(days=MISS_DAYS)).isoformat()
    misses = {} if force or not MISSES.exists() else json.loads(MISSES.read_text(encoding="utf-8"))
    stats = {"am": 0, "img": 0, "both": 0, "none": 0}
    searched = skipped_misses = reused = 0
    next_save = SAVE_EVERY
    # normalized name -> an entry that already has an Apple Music link
    linked = {norm(name): e for name, e in artists.items() if "appleMusicUrl" in e}
    blocked = None
    for billing in billings:
        # Fill what an entry is missing (a Spotify-only entry still gets
        # its Apple Music link and photo looked up).
        if "appleMusicUrl" in artists.get(billing, {}):
            continue
        recent_miss = misses.get(billing, "") >= cutoff
        if recent_miss:
            skipped_misses += 1
        entry = dict(artists.get(billing, {}))
        # Reuse before searching: the same artist already linked under
        # another spelling ("Artbat" / "ARTBAT"), or, for "A b2b B", the
        # first-billed act's own entry (it supplies the billing's fields).
        for cand in candidates(billing):
            known = linked.get(norm(cand))
            if known:
                for field in ("appleMusicUrl", "imageUrl"):
                    if field in known and field not in entry:
                        entry[field] = known[field]
                reused += 1
                break
        answered = True  # every search for this billing got an answer
        for cand in candidates(billing):
            if "appleMusicUrl" not in entry and not recent_miss and not blocked:
                if lookup_key(cand) not in _cache:
                    searched += 1
                try:
                    found = itunes_artist_url(cand)
                except LookupBlocked as exc:
                    blocked, found = str(exc), None
                    print(f"apple music search keeps failing ({blocked}); "
                          "stopping the search for this run", file=sys.stderr)
                if lookup_key(cand) not in _cache:
                    answered = False
                if found:
                    entry["appleMusicUrl"] = found
            if "imageUrl" not in entry and norm(cand) in slugs:
                entry["imageUrl"] = slugs[norm(cand)]
            if "appleMusicUrl" in entry and "imageUrl" in entry:
                break
        if entry:
            artists[billing] = entry
        if "appleMusicUrl" in entry:
            linked.setdefault(norm(billing), entry)
            misses.pop(billing, None)
        elif answered and not recent_miss and not blocked:
            misses[billing] = today
        if searched >= next_save:
            save(config, artists, misses)
            next_save = (searched // SAVE_EVERY + 1) * SAVE_EVERY
        if "appleMusicUrl" in entry:
            stats["am"] += 1
        if "imageUrl" in entry:
            stats["img"] += 1
        if "appleMusicUrl" in entry and "imageUrl" in entry:
            stats["both"] += 1
        if not entry:
            stats["none"] += 1

    # Apple Music artwork, for every artist with a link and no photo.
    want_art = {
        billing: apple_music_artist_id(entry["appleMusicUrl"])
        for billing, entry in artists.items()
        if "imageUrl" not in entry and "appleMusicUrl" in entry
    }
    want_art = {b: i for b, i in want_art.items() if i}
    artwork = apple_music_artwork(want_art.values()) if want_art else {}
    added_art = 0
    for billing, artist_id in want_art.items():
        if artist_id in artwork:
            artists[billing]["imageUrl"] = artwork[artist_id]
            added_art += 1
    print(f"apple music photos: {added_art} of {len(want_art)} artists without one")

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

    save(config, artists, misses)
    print(f"apple music: searched {searched} names, reused {reused} existing "
          f"entries, skipped {skipped_misses} "
          f"not found in the last {MISS_DAYS} days"
          + (f"; search stopped early: {blocked}" if blocked else ""))
    print(f"artists entries: {len(artists)} "
          f"(appleMusic {stats['am']}, images {stats['img']}, "
          f"both {stats['both']}, unmatched-new {stats['none']})")
    return 1 if blocked else 0


_bump: dict = {}


def save(config, artists, misses) -> None:
    """Write the artists map (and meta) to the config, and the misses file."""
    config["artists"] = dict(sorted(artists.items()))
    from datetime import datetime, timezone
    # One bump per branch: main's version + 1, however often this runs
    # (worked out once per run, since a run saves more than once).
    if "version" not in _bump:
        try:
            import subprocess
            main_doc = subprocess.run(
                ["git", "show", "origin/main:v2/config.json"], cwd=ROOT,
                capture_output=True, text=True, check=True).stdout
            _bump["version"] = int(json.loads(main_doc)["meta"]["version"]) + 1
        except Exception:  # noqa: BLE001 - no git or no origin/main: plain bump
            _bump["version"] = int(config["meta"].get("version", 1)) + 1
    config["meta"]["version"] = _bump["version"]
    config["meta"]["publishedAt"] = (
        datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    CONFIG.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n",
                      encoding="utf-8")
    MISSES.write_text(json.dumps(dict(sorted(misses.items())), indent=2,
                                 ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
