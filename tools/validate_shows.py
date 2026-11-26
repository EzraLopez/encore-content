#!/usr/bin/env python3
"""Validate the hand-kept show lists (shows/*.json).

Dependency-free. Usage: python3 tools/validate_shows.py [path ...]
With no argument it checks every file in shows/. Exit code 0 means the files
are safe to publish; problems are printed to stderr and the exit code is 1.
The cityShows function (encore-android functions/curatedShows.js) reads these
files and drops any row it can't use, so a mistake here loses a show quietly:
run this before pushing.
"""

import json
import re
import sys
from datetime import date
from pathlib import Path

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
ALLOWED = {"title", "date", "startTime", "venue", "venueLocation", "venueAddress", "artists", "genres", "ages", "link", "found"}
REQUIRED = ("title", "date", "venue", "venueLocation", "link")
MAX_SHOWS = 300

errors = []


def err(path, msg):
    errors.append(f"{path}: {msg}")


def check(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        err(path, f"not readable JSON: {e}")
        return
    if not isinstance(data, dict) or not isinstance(data.get("region"), int):
        err(path, "needs an integer `region` (the city's id in showSources.js)")
        return
    if not DATE_RE.match(str(data.get("updatedAt", ""))):
        err(path, "`updatedAt` must be YYYY-MM-DD")
    shows = data.get("shows")
    if not isinstance(shows, list):
        err(path, "`shows` must be a list")
        return
    if len(shows) > MAX_SHOWS:
        err(path, f"more than {MAX_SHOWS} shows")
    seen = set()
    for i, s in enumerate(shows):
        where = f"shows[{i}]" + (f" ({s.get('title')})" if isinstance(s, dict) else "")
        if not isinstance(s, dict):
            err(path, f"{where}: not an object")
            continue
        for k in set(s) - ALLOWED:
            err(path, f"{where}: unknown field `{k}`")
        for k in REQUIRED:
            if not isinstance(s.get(k), str) or not s[k].strip():
                err(path, f"{where}: `{k}` is required")
        d = s.get("date")
        if isinstance(d, str):
            if not DATE_RE.match(d):
                err(path, f"{where}: `date` must be YYYY-MM-DD")
            else:
                try:
                    date.fromisoformat(d)
                except ValueError:
                    err(path, f"{where}: `date` is not a real day")
        if "startTime" in s and not (isinstance(s["startTime"], str) and TIME_RE.match(s["startTime"])):
            err(path, f"{where}: `startTime` must be HH:MM (24 hour), or left out")
        for k in ("link", "found"):
            if k in s and not (isinstance(s[k], str) and s[k].startswith("https://")):
                err(path, f"{where}: `{k}` must be an https link")
        if "artists" in s and not (isinstance(s["artists"], list) and all(isinstance(a, str) and a.strip() for a in s["artists"])):
            err(path, f"{where}: `artists` must be a list of names")
        for k in ("genres", "ages", "venueAddress"):
            if k in s and not (isinstance(s[k], str) and s[k].strip()):
                err(path, f"{where}: `{k}` must be text, or left out")
        key = (s.get("date"), str(s.get("venue", "")).lower(), str(s.get("title", "")).lower())
        if key in seen:
            err(path, f"{where}: listed twice")
        seen.add(key)


def main():
    root = Path(__file__).resolve().parent.parent
    paths = sys.argv[1:] or sorted(str(p) for p in (root / "shows").glob("*.json"))
    if not paths:
        print("no show lists found", file=sys.stderr)
        return 1
    for p in paths:
        check(p)
    for e in errors:
        print(e, file=sys.stderr)
    if not errors:
        print(f"ok: {len(paths)} list(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
