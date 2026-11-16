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
    python3 tools/watch_instagram.py [--date YYYY-MM-DD] [--dry-run] [--file-changes]

--file-changes (what the hourly LaunchAgent runs, Nov 15, 2026): reads
the live catalog, remembers which posts it has seen
(~/.config/katla/instagram-seen.json), and files each NEW post that
looks like a schedule change or cancellation as a festival change report
(Firestore `feedback`, kind "change", platform "watcher", with the
post's image), the same as Report a Change in the apps. The queue keeper
routine turns reports into proposed catalog changes for Ezra. Nothing
here edits the catalog.
"""

import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import time
import uuid
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
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
LIVE_CONFIG = "https://raw.githubusercontent.com/EzraLopez/encore-content/main/v2/config.json"
SEEN_FILE = Path.home() / ".config" / "katla" / "instagram-seen.json"
FEEDBACK_URL = (
    "https://firestore.googleapis.com/v1/projects/encore-ca65a/databases/(default)/documents/feedback"
)
# The backend's limit for a report's picture (firestore.rules, feedback).
MAX_IMAGE_BYTES = 400_000
# An account seen for the first time: only posts this recent are news.
FIRST_SIGHT_HOURS = 48
# Words festivals use when the plan changes. A post without any of them
# (merch, recaps, promos) is not reported.
CHANGE_RE = re.compile(
    r"set[\s-]?times?|schedule|timetable|cancel|postpon|delay|weather|evacuat|lightning|"
    r"storm|rain|wind|heat|closed|closure|shelter|moved|swap|updated?|change|replac|"
    r"no longer|unable to|won.t be|will not|doors|gates|re-?entry|do not travel|refund|lineup",
    re.IGNORECASE,
)


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
        "{id,caption,permalink,timestamp,media_type,media_url,thumbnail_url}}"
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
                "id": item.get("id"),
                "imageUrl": item.get("media_url") if item.get("media_type") != "VIDEO" else item.get("thumbnail_url"),
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


# ---- Filing new posts as change reports ------------------------------

def looks_like_change(caption):
    """True when a caption uses the words festivals use for changes."""
    return bool(caption) and bool(CHANGE_RE.search(caption))


def post_time(post):
    """The post's time, or None. Instagram writes 2026-11-15T22:15:03+0000."""
    stamp = post.get("timestamp") or ""
    try:
        return datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%S%z")
    except ValueError:
        return None


def new_posts(seen, username, posts, now, first_sight_hours=FIRST_SIGHT_HOURS):
    """The posts not seen before, oldest first.

    `seen` maps username to the permalinks already handled. For an account
    seen for the first time, only posts from the last `first_sight_hours`
    are new: older ones are history, not news."""
    known = set(seen.get(username, []))
    first_sight = username not in seen
    fresh = []
    for post in posts:
        link = post.get("permalink")
        if not link or link in known:
            continue
        if first_sight:
            when = post_time(post)
            if when is None or now - when > timedelta(hours=first_sight_hours):
                continue
        fresh.append(post)
    fresh.sort(key=lambda p: p.get("timestamp") or "")
    return fresh


def remember(seen, username, posts, keep=200):
    """`seen` with these posts' permalinks added (newest `keep` kept)."""
    links = list(seen.get(username, []))
    for post in posts:
        link = post.get("permalink")
        if link and link not in links:
            links.append(link)
    out = dict(seen)
    out[username] = links[-keep:]
    return out


def change_report_message(username, post):
    """What the queue keeper reads: who posted, when, the caption, the link."""
    caption = (post.get("caption") or "").strip() or "(no caption)"
    text = f"From Instagram @{username} ({post.get('timestamp') or 'time unknown'}):\n{caption}\n{post.get('permalink') or ''}"
    return text[:2000]


def change_report_document(festival_id, username, post, image, now_ms, catalog_version=None):
    """A Firestore REST document for `feedback`, in the shape the rules accept."""
    fields = {
        "reportId": {"stringValue": str(uuid.uuid4())},
        "kind": {"stringValue": "change"},
        "message": {"stringValue": change_report_message(username, post)},
        "platform": {"stringValue": "watcher"},
        "appVersion": {"stringValue": "instagram-watch"},
        "build": {"stringValue": "1"},
        "osVersion": {"stringValue": "macOS"},
        "device": {"stringValue": "Katla Mac"},
        "screen": {"stringValue": f"festival:{festival_id}"[:120]},
        "createdAt": {"integerValue": str(int(now_ms))},
    }
    if isinstance(catalog_version, int):
        fields["catalogVersion"] = {"integerValue": str(catalog_version)}
    if image and len(image) <= MAX_IMAGE_BYTES:
        import base64

        fields["screenshot"] = {"bytesValue": base64.b64encode(image).decode()}
    return {"fields": fields}


def shrink_to_jpeg(data, limit=MAX_IMAGE_BYTES):
    """A JPEG of `data` under `limit` bytes (macOS sips), or None."""
    with tempfile.TemporaryDirectory() as folder:
        source = Path(folder) / "post"
        source.write_bytes(data)
        for side, quality in ((1280, 70), (1080, 60), (900, 50), (720, 45)):
            out = Path(folder) / f"post-{side}.jpg"
            result = subprocess.run(
                ["/usr/bin/sips", "-s", "format", "jpeg", "-s", "formatOptions", str(quality),
                 "-Z", str(side), str(source), "--out", str(out)],
                capture_output=True,
            )
            if result.returncode == 0 and out.is_file() and out.stat().st_size <= limit:
                return out.read_bytes()
    return None


def fetch_image(url, opener):
    if not url or not url.startswith("https://"):
        return None
    try:
        with opener(urllib.request.Request(url, headers={"User-Agent": "encore-instagram-watch"}), timeout=20) as r:
            data = r.read(8_000_000)
    except (urllib.error.URLError, OSError):
        return None
    try:
        return shrink_to_jpeg(data)
    except OSError:
        return None


def post_report(document, opener):
    """Create the report. The rules let anyone create one; nothing else."""
    request = urllib.request.Request(
        FEEDBACK_URL,
        data=json.dumps(document).encode(),
        headers={"Content-Type": "application/json", "User-Agent": "encore-instagram-watch"},
        method="POST",
    )
    try:
        with opener(request, timeout=20) as response:
            response.read()
    except urllib.error.HTTPError as exc:
        raise WatchError(f"report refused (HTTP {exc.code}): {exc.read().decode('utf-8', 'replace')[:200]}") from exc
    except urllib.error.URLError as exc:
        raise WatchError(f"report not sent: {exc.reason}") from exc


def load_seen(path=SEEN_FILE):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_seen(seen, path=SEEN_FILE):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(seen, indent=2), encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(path)


def file_changes(report, seen, now, opener, catalog_version=None, post=None):
    """Report each new, change-like post once. Returns (filed, updated seen).

    A post is marked seen only once it is handled (filed, or not
    change-like), so a report that fails to send is retried next run."""
    post = post or (lambda doc: post_report(doc, opener))
    filed = []
    for row in report["festivals"]:
        if not row.get("ok"):
            continue
        username = row["username"]
        fresh = new_posts(seen, username, row["posts"], now)
        unsent = []
        for item in fresh:
            if looks_like_change(item.get("caption")):
                image = fetch_image(item.get("imageUrl"), opener)
                doc = change_report_document(row["id"], username, item, image, now.timestamp() * 1000, catalog_version)
                try:
                    post(doc)
                except WatchError as exc:
                    print(f"failed to file {item.get('permalink')}: {exc}", file=sys.stderr)
                    unsent.append(item)
                    continue
                filed.append({"festival": row["id"], "permalink": item.get("permalink")})
        # Every current post is known now, except reports that failed to send.
        seen = remember(seen, username, [p for p in row["posts"] if p not in unsent])
    return filed, seen


def load_live_config(opener):
    """The published catalog, so the watch follows merges without a pull."""
    with opener(urllib.request.Request(LIVE_CONFIG, headers={"User-Agent": "encore-instagram-watch"}), timeout=20) as r:
        payload = json.loads(r.read())
    festivals = payload.get("festivals") if isinstance(payload, dict) else None
    if not isinstance(festivals, list):
        raise WatchError("the live catalog has no festivals array")
    return festivals, (payload.get("meta") or {}).get("version")


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
    filing = "--file-changes" in args
    if filing:
        args.remove("--file-changes")
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
    catalog_version = None
    try:
        if filing and config_path == CONFIG:
            try:
                festivals, catalog_version = load_live_config(urllib.request.urlopen)
            except (WatchError, OSError, ValueError) as exc:
                print(f"live catalog unavailable ({exc}); using the local copy", file=sys.stderr)
                festivals = load_config(config_path)
        else:
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
    if filing:
        now = datetime.now(timezone.utc)
        print(f"{now.isoformat(timespec='seconds')} checked {len(report['festivals'])} festival(s)", file=sys.stderr)
        filed, seen = file_changes(report, load_seen(), now, urllib.request.urlopen, catalog_version)
        save_seen(seen)
        for item in filed:
            print(f"filed change report: {item['festival']} {item['permalink']}", file=sys.stderr)
    else:
        print(json.dumps(report, indent=2))
    for row in report["festivals"]:
        if row["ok"]:
            print(f"ok {row['id']} @{row['username']} {len(row['posts'])} posts", file=sys.stderr)
        else:
            print(f"failed {row['id']}: {row.get('error')}", file=sys.stderr)
    return 1 if report["failed"] else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
