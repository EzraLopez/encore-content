#!/usr/bin/env python3
"""Validate an Encore v2 remote-config file (v2/config.json).

Dependency-free (Python 3 standard library only).

Usage:
    python3 tools/validate_config.py [path]

With no argument it validates the v2/config.json in this repo. Exit code 0
means the file is safe to publish; any problem is printed to stderr and the
exit code is 1. Publishing a config that fails validation can break the
apps' content diffing and notifications, so always run this before pushing.
"""

import json
import re
import sys
from datetime import date, datetime
from pathlib import Path

TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
ACCENT_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
# Two different festivals' accents must sit at least this far apart
# (CIE76 delta E) to tell their cards apart; the apps' own tests hold
# the colors they ship to the same number.
MIN_ACCENT_DISTANCE = 30.0

errors = []


def err(msg):
    errors.append(msg)


def parse_iso_datetime(value):
    """Parse an ISO-8601 datetime, tolerating a trailing 'Z'. None on failure."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def parse_date(value):
    if not isinstance(value, str) or not DATE_RE.match(value):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def tz_database_available():
    try:
        from zoneinfo import ZoneInfo

        ZoneInfo("UTC")
        return True
    except Exception:
        return False


TZ_CHECK = tz_database_available()


def check_timezone(value, where):
    if not isinstance(value, str) or not value.strip():
        err(f"{where}: missing or empty 'timezone' (an IANA name like 'America/Chicago' is required)")
        return
    if TZ_CHECK:
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            err(f"{where}: timezone {value!r} is not a known IANA timezone")


def require_str(obj, field, where):
    value = obj.get(field)
    if not isinstance(value, str) or not value.strip():
        err(f"{where}: missing or empty required field {field!r}")
        return None
    return value


def lab(hex_color):
    """'#RRGGBB' -> CIE L*a*b* (D65), for a perceptual distance."""
    def linear(channel):
        return channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4

    r, g, b = (linear(int(hex_color[i:i + 2], 16) / 255) for i in (1, 3, 5))
    x = (0.4124 * r + 0.3576 * g + 0.1805 * b) / 0.95047
    y = 0.2126 * r + 0.7152 * g + 0.0722 * b
    z = (0.0193 * r + 0.1192 * g + 0.9505 * b) / 1.08883

    def f(t):
        return t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116

    return (116 * f(y) - 16, 500 * (f(x) - f(y)), 200 * (f(y) - f(z)))


def site_host(fest):
    """The festival's website host, lowercased, without a leading 'www.'."""
    url = fest.get("websiteUrl")
    if not isinstance(url, str):
        return None
    match = re.match(r"^https?://([^/]+)", url.strip().lower())
    if not match:
        return None
    host = match.group(1)
    return host[4:] if host.startswith("www.") else host


def validate_requested_as(festivals):
    """requestedAs is optional; when present it is a list of non-empty
    strings (the names people asked for the festival by). Android reads
    it strictly: a wrong type there would cost the whole catalog."""
    for fest in festivals:
        if not isinstance(fest, dict) or "requestedAs" not in fest:
            continue
        value = fest["requestedAs"]
        where = f"festival {fest.get('id')!r}"
        if not isinstance(value, list) or not all(
            isinstance(name, str) and name.strip() for name in value
        ):
            err(f"{where}: requestedAs must be a list of non-empty strings")


def validate_accents(festivals):
    """accentColor is optional; when present it is '#RRGGBB', and two
    festivals share (or nearly share) one only when they are the same
    event brand, which is read off the website host (two weekends of
    one festival)."""
    valid = []
    for fest in festivals:
        if not isinstance(fest, dict) or "accentColor" not in fest:
            continue
        where = f"festival {fest.get('id')!r}"
        value = fest["accentColor"]
        if not isinstance(value, str) or not ACCENT_RE.match(value):
            err(f"{where}: accentColor {value!r} is not a '#RRGGBB' color")
            continue
        valid.append(fest)
    for i, first in enumerate(valid):
        for second in valid[i + 1:]:
            host = site_host(first)
            if host is not None and host == site_host(second):
                continue
            a, b = lab(first["accentColor"]), lab(second["accentColor"])
            distance = sum((p - q) ** 2 for p, q in zip(a, b)) ** 0.5
            if distance < MIN_ACCENT_DISTANCE:
                err(f"festival {first.get('id')!r} and {second.get('id')!r}: accentColor "
                    f"{first['accentColor']} and {second['accentColor']} are too close to tell "
                    f"apart (delta E {distance:.1f}, need {MIN_ACCENT_DISTANCE:.0f}); "
                    "pick another color from one festival's branding")


def validate_set(s, where):
    if not isinstance(s, dict):
        err(f"{where}: set is not an object")
        return
    require_str(s, "id", where)
    require_str(s, "artist", where)
    start, end = s.get("start"), s.get("end")
    for label, value in (("start", start), ("end", end)):
        if not isinstance(value, str) or not TIME_RE.match(value):
            err(f"{where}: set {label} time {value!r} is not 24h 'HH:mm'")
    if isinstance(start, str) and isinstance(end, str) and start == end:
        err(f"{where}: set has start == end ({start}); zero-length sets are invalid "
            "(an overnight set must end after midnight, e.g. start '23:30', end '01:00')")


def validate_festival(fest, index, seen_ids, seen_set_ids):
    where = f"festivals[{index}]"
    if not isinstance(fest, dict):
        err(f"{where}: festival is not an object")
        return
    fid = require_str(fest, "id", where)
    if fid:
        where = f"festival {fid!r}"
        if fid in seen_ids:
            err(f"{where}: duplicate festival id {fid!r} — ids must be unique; "
                "favorites and RSVPs are keyed off them")
        seen_ids.add(fid)
    require_str(fest, "name", where)
    check_timezone(fest.get("timezone"), where)

    start = fest.get("startDate")
    end = fest.get("endDate")
    start_d, end_d = parse_date(start), parse_date(end)
    if start_d is None:
        err(f"{where}: startDate {start!r} is not a valid 'YYYY-MM-DD' date")
    if end_d is None:
        err(f"{where}: endDate {end!r} is not a valid 'YYYY-MM-DD' date")
    if start_d and end_d and end_d < start_d:
        err(f"{where}: endDate {end} is before startDate {start}")

    days = fest.get("days")
    if not isinstance(days, list):
        err(f"{where}: 'days' must be an array (use [] when the lineup is TBA)")
        return
    for di, day in enumerate(days):
        dwhere = f"{where} days[{di}]"
        if not isinstance(day, dict):
            err(f"{dwhere}: day is not an object")
            continue
        if parse_date(day.get("date")) is None:
            err(f"{dwhere}: date {day.get('date')!r} is not a valid 'YYYY-MM-DD' date")
        stages = day.get("stages")
        if not isinstance(stages, list):
            err(f"{dwhere}: 'stages' must be an array")
            continue
        for si, stage in enumerate(stages):
            swhere = f"{dwhere} stages[{si}]"
            if not isinstance(stage, dict):
                err(f"{swhere}: stage is not an object")
                continue
            sname = require_str(stage, "name", swhere)
            if sname:
                swhere = f"{dwhere} stage {sname!r}"
            sets = stage.get("sets")
            if not isinstance(sets, list):
                err(f"{swhere}: 'sets' must be an array")
                continue
            for ti, s in enumerate(sets):
                validate_set(s, f"{swhere} sets[{ti}]")
                if isinstance(s, dict) and isinstance(s.get("id"), str):
                    if s["id"] in seen_set_ids:
                        err(f"{swhere}: duplicate set id {s['id']!r} — set ids must be "
                            "unique; favorites are keyed off them")
                    seen_set_ids.add(s["id"])
    validate_lineup(fest, where, start_d, end_d, seen_set_ids)


def validate_lineup(fest, where, start_d, end_d, seen_set_ids):
    """`lineup` is optional: artists announced before their set times.
    Each entry is {id, artist, day?, stage?}; ids share the set-id
    namespace (a favourite keys off them) and an entry keeps its id
    when it moves into `days` with a time, so it must not ALSO appear
    as a set; `day` falls within the festival's dates."""
    lineup = fest.get("lineup")
    if lineup is None:
        return
    if not isinstance(lineup, list):
        err(f"{where}: 'lineup' must be an array of {{id, artist, day?, stage?}}")
        return
    for li, entry in enumerate(lineup):
        lwhere = f"{where} lineup[{li}]"
        if not isinstance(entry, dict):
            err(f"{lwhere}: entry is not an object")
            continue
        lid = require_str(entry, "id", lwhere)
        require_str(entry, "artist", lwhere)
        if lid:
            if lid in seen_set_ids:
                err(f"{lwhere}: id {lid!r} is already a set id; when an artist gets a "
                    "time, move the entry into 'days' (same id) and remove it here")
            seen_set_ids.add(lid)
        day = entry.get("day")
        if day is not None:
            d = parse_date(day)
            if d is None:
                err(f"{lwhere}: day {day!r} is not a valid 'YYYY-MM-DD' date")
            elif start_d and end_d and not (start_d <= d <= end_d):
                err(f"{lwhere}: day {day} is outside the festival's dates")
        stage = entry.get("stage")
        if stage is not None and (not isinstance(stage, str) or not stage.strip()):
            err(f"{lwhere}: stage must be a non-empty string when present")


def validate_show(show, index, seen_ids):
    where = f"shows[{index}]"
    if not isinstance(show, dict):
        err(f"{where}: show is not an object")
        return
    sid = require_str(show, "id", where)
    if sid:
        where = f"show {sid!r}"
        if sid in seen_ids:
            err(f"{where}: duplicate id {sid!r} — ids must be unique across festivals and shows")
        seen_ids.add(sid)
    require_str(show, "artist", where)
    require_str(show, "venue", where)
    require_str(show, "city", where)
    check_timezone(show.get("timezone"), where)
    start = show.get("start")
    parsed = parse_iso_datetime(start)
    if parsed is None or "T" not in str(start):
        err(f"{where}: start {start!r} is not an ISO local datetime (e.g. '2026-11-28T23:00:00')")


def validate(path):
    try:
        with open(path, encoding="utf-8") as f:
            config = json.load(f)
    except FileNotFoundError:
        print(f"ERROR: file not found: {path}", file=sys.stderr)
        return 1
    except json.JSONDecodeError as e:
        print(f"ERROR: {path} is not valid JSON: {e}", file=sys.stderr)
        return 1

    if not isinstance(config, dict):
        err("top level: config must be a JSON object with 'meta', 'festivals', and 'shows'")
        config = {}

    meta = config.get("meta")
    if not isinstance(meta, dict):
        err("meta: missing or not an object — the envelope requires meta.version and meta.publishedAt")
        meta = {}
    version = meta.get("version")
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        err(f"meta.version: must be a positive integer, got {version!r}")
    if parse_iso_datetime(meta.get("publishedAt")) is None:
        err(f"meta.publishedAt: {meta.get('publishedAt')!r} does not parse as an ISO-8601 datetime")

    festivals = config.get("festivals")
    if not isinstance(festivals, list):
        err("festivals: missing or not an array")
        festivals = []
    shows = config.get("shows")
    if not isinstance(shows, list):
        err("shows: missing or not an array (use [] when there are no remote shows)")
        shows = []

    seen_ids = set()
    seen_set_ids = set()
    for i, fest in enumerate(festivals):
        validate_festival(fest, i, seen_ids, seen_set_ids)
    for i, show in enumerate(shows):
        validate_show(show, i, seen_ids)
    validate_accents(festivals)
    validate_requested_as(festivals)

    # Optional per-artist enrichment (Apple Music artist pages and
    # profile photos). Apps ignore it when absent, and ignore
    # entries they don't recognise; only the value shapes are
    # checked so a malformed URL can never reach a tap handler.
    artists = config.get("artists", {})
    if not isinstance(artists, dict):
        err("artists: must be an object keyed by artist billing when present")
        artists = {}
    for name, entry in artists.items():
        where = f"artists[{name!r}]"
        if not isinstance(entry, dict) or not entry:
            err(f"{where}: entry must be a non-empty object")
            continue
        for field in ("appleMusicUrl", "imageUrl"):
            value = entry.get(field)
            if value is None:
                continue
            if not isinstance(value, str) or not value.startswith("https://"):
                err(f"{where}: {field} {value!r} is not an https URL")
        if "appleMusicUrl" in entry and not str(
                entry["appleMusicUrl"]).startswith("https://music.apple.com/"):
            err(f"{where}: appleMusicUrl must be a music.apple.com artist page")

    if errors:
        print(f"INVALID: {path} failed validation with {len(errors)} error(s):", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1

    n_sets = sum(
        len(stage.get("sets", []))
        for fest in festivals
        for day in fest.get("days", [])
        for stage in day.get("stages", [])
    )
    print(f"OK: {path} is valid — meta.version {version}, "
          f"{len(festivals)} festival(s), {n_sets} set(s), {len(shows)} show(s).")
    return 0


def main():
    if len(sys.argv) > 1:
        path = Path(sys.argv[1])
    else:
        path = Path(__file__).resolve().parent.parent / "v2" / "config.json"
    return validate(path)


if __name__ == "__main__":
    sys.exit(main())
