#!/usr/bin/env python3
"""Collect public Instagram feed posts for festivals that are on.

Festivals post set-time changes and cancellations on Instagram. This
reads those feed posts through Meta's Business Discovery API and prints
a JSON report. It never edits the catalog and never publishes.

It needs two values this repo does not hold:

  KATLA_IG_TOKEN    a Facebook user token with instagram_basic,
                    instagram_manage_insights and pages_read_engagement
                    (pages_show_list is required to find the Page).
                    Or the same text in ~/.config/katla/meta-token,
                    mode 600.
  KATLA_IG_USER_ID  the Instagram user id of the Katla business account
                    that makes the query. Or ~/.config/katla/ig-user-id.

Usage:
    python3 tools/watch_instagram.py [--date YYYY-MM-DD] [--dry-run]
"""

import json
import os
import re
import stat
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "v2" / "config.json"
TOKEN_FILE = Path.home() / ".config" / "katla" / "meta-token"
IG_USER_FILE = Path.home() / ".config" / "katla" / "ig-user-id"
GRAPH = "https://graph.facebook.com/v21.0"
MEDIA_LIMIT = 8
# The night before a festival is when cancellations tend to land.
LEAD_DAYS = 1
USERNAME_RE = re.compile(r"^[A-Za-z0-9._]{1,30}$")
HANDLE_RE = re.compile(
    r"^https?://(?:www\.)?instagram\.com/([A-Za-z0-9._]{1,30})/?$",
    re.IGNORECASE,
)
TOKEN_RE = re.compile(r"(access_token=)[^&\s]+", re.IGNORECASE)


class WatchError(Exception):
    """A check that could not be completed. The message never contains a token."""


def redact(text):
    return TOKEN_RE.sub(r"\1[redacted]", text or "")


def instagram_username(url):
    """The account in a profile URL, or None for a post, reel, or empty link."""
    if not isinstance(url, str) or not url.strip():
        return None
    path = url.strip().split("?", 1)[0].split("#", 1)[0]
    match = HANDLE_RE.match(path)
    if not match:
        return None
    username = match.group(1)
    if username.lower() in {"p", "reel", "reels", "stories", "explore", "accounts"}:
        return None
    return username


def on_watch(festival, today, lead_days=LEAD_DAYS):
    """True from `lead_days` before the first day through the last day."""
    try:
        start = date.fromisoformat(festival["startDate"])
        end = date.fromisoformat(festival["endDate"])
    except (KeyError, TypeError, ValueError):
        return False
    return start - timedelta(days=lead_days) <= today <= end


def festivals_due(festivals, today, lead_days=LEAD_DAYS):
    due = []
    for festival in festivals:
        if not on_watch(festival, today, lead_days):
            continue
        due.append(
            {
                "id": festival.get("id"),
                "name": festival.get("name"),
                "username": instagram_username(festival.get("instagramUrl")),
                "instagramUrl": festival.get("instagramUrl"),
            }
        )
    return due


def _owner_only(path):
    info = path.stat()
    if info.st_uid != os.getuid():
        return False
    return stat.S_IMODE(info.st_mode) == 0o600


def read_secret_file(path):
    """Read a mode-600 file. Refuse anything another user could read."""
    if not path.is_file():
        return None
    if not _owner_only(path):
        raise WatchError(f"{path} must be mode 600 and owned by you")
    text = path.read_text(encoding="utf-8").strip()
    return text or None


def load_token():
    env = os.environ.get("KATLA_IG_TOKEN", "").strip()
    if env:
        return env
    return read_secret_file(TOKEN_FILE)


def load_ig_user_id():
    env = os.environ.get("KATLA_IG_USER_ID", "").strip()
    if env:
        return env
    if not IG_USER_FILE.is_file():
        return None
    text = IG_USER_FILE.read_text(encoding="utf-8").strip()
    return text or None


def discovery_url(ig_user_id, username):
    if not USERNAME_RE.fullmatch(username or ""):
        raise WatchError(f"not an Instagram username: {username!r}")
    if not re.fullmatch(r"\d+", ig_user_id or ""):
        raise WatchError("KATLA_IG_USER_ID must be the numeric Instagram user id")
    fields = (
        f"business_discovery.username({username})"
        f"{{username,media.limit({MEDIA_LIMIT})"
        "{caption,permalink,timestamp,media_type}}"
    )
    query = urllib.parse.urlencode({"fields": fields})
    return f"{GRAPH}/{ig_user_id}?{query}"


def parse_discovery(body):
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise WatchError(f"Instagram returned non-JSON: {exc}") from exc
    if isinstance(payload, dict) and payload.get("error"):
        message = payload["error"].get("message") or "Instagram refused the request"
        raise WatchError(redact(str(message)))
    discovery = payload.get("business_discovery") if isinstance(payload, dict) else None
    if not isinstance(discovery, dict):
        raise WatchError("Instagram returned no business_discovery object")
    media = discovery.get("media") or {}
    items = media.get("data") if isinstance(media, dict) else None
    posts = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        caption = item.get("caption")
        if isinstance(caption, str) and len(caption) > 500:
            caption = caption[:500]
        posts.append(
            {
                "permalink": item.get("permalink"),
                "timestamp": item.get("timestamp"),
                "mediaType": item.get("media_type"),
                "caption": caption,
            }
        )
    return {"username": discovery.get("username"), "posts": posts}


def fetch_discovery(ig_user_id, username, token, opener):
    url = discovery_url(ig_user_id, username) + "&" + urllib.parse.urlencode(
        {"access_token": token}
    )
    request = urllib.request.Request(url, headers={"User-Agent": "encore-instagram-watch"})
    try:
        with opener(request, timeout=20) as response:
            body = response.read()
    except urllib.error.HTTPError as exc:
        detail = redact(exc.read().decode("utf-8", "replace")[:300])
        raise WatchError(f"HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise WatchError(redact(str(exc.reason))) from exc
    return parse_discovery(body)


def build_report(festivals, today, token, ig_user_id, opener, lead_days=LEAD_DAYS):
    """One entry per due festival. Shared accounts are queried once."""
    due = festivals_due(festivals, today, lead_days)
    cache = {}
    rows = []
    for festival in due:
        username = festival["username"]
        row = {
            "id": festival["id"],
            "name": festival["name"],
            "username": username,
            "ok": False,
            "posts": [],
        }
        if not username:
            row["error"] = "no Instagram profile URL"
            rows.append(row)
            continue
        if username not in cache:
            if not token:
                cache[username] = WatchError("no token (KATLA_IG_TOKEN or ~/.config/katla/meta-token)")
            elif not ig_user_id:
                cache[username] = WatchError("no Instagram user id (KATLA_IG_USER_ID or ~/.config/katla/ig-user-id)")
            else:
                try:
                    cache[username] = fetch_discovery(ig_user_id, username, token, opener)
                except WatchError as exc:
                    cache[username] = exc
        found = cache[username]
        if isinstance(found, WatchError):
            row["error"] = str(found)
        else:
            row["ok"] = True
            row["posts"] = found["posts"]
        rows.append(row)
    failed = [row["id"] for row in rows if not row["ok"]]
    return {
        "checkedOn": today.isoformat(),
        "leadDays": lead_days,
        "festivals": rows,
        "failed": failed,
    }


def load_config(path):
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WatchError(f"cannot read {path}: {exc}") from exc
    festivals = payload.get("festivals") if isinstance(payload, dict) else None
    if not isinstance(festivals, list):
        raise WatchError(f"{path} has no festivals array")
    return festivals


def main(argv):
    args = list(argv)
    dry_run = "--dry-run" in args
    if dry_run:
        args.remove("--dry-run")
    config_path = CONFIG
    today = date.today()
    lead_days = LEAD_DAYS
    index = 0
    while index < len(args):
        flag = args[index]
        if flag == "--config" and index + 1 < len(args):
            config_path = Path(args[index + 1])
            index += 2
            continue
        if flag == "--date" and index + 1 < len(args):
            try:
                today = date.fromisoformat(args[index + 1])
            except ValueError:
                print(f"not a date: {args[index + 1]}", file=sys.stderr)
                return 2
            index += 2
            continue
        if flag == "--lead-days" and index + 1 < len(args):
            try:
                lead_days = int(args[index + 1])
            except ValueError:
                print(f"not an integer: {args[index + 1]}", file=sys.stderr)
                return 2
            index += 2
            continue
        print(f"unknown argument: {flag}", file=sys.stderr)
        return 2
    try:
        festivals = load_config(config_path)
    except WatchError as exc:
        print(exc, file=sys.stderr)
        return 1
    if dry_run:
        due = festivals_due(festivals, today, lead_days)
        print(json.dumps({"checkedOn": today.isoformat(), "dryRun": True, "festivals": due}, indent=2))
        return 0
    try:
        token = load_token()
        ig_user_id = load_ig_user_id()
        report = build_report(
            festivals, today, token, ig_user_id, urllib.request.urlopen, lead_days
        )
    except WatchError as exc:
        print(exc, file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2))
    for row in report["festivals"]:
        if row["ok"]:
            print(f"ok {row['id']} @{row['username']} {len(row['posts'])} posts", file=sys.stderr)
        else:
            print(f"failed {row['id']}: {row.get('error')}", file=sys.stderr)
    return 1 if report["failed"] else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
