#!/usr/bin/env python3
"""Check Instagram handles before they go in the catalog.

    python3 tools/check_instagram.py coachella outsidelands

Looks each handle up through Meta's Business Discovery with the watch's
token (see watch_instagram.py) and prints the account's name, followers
and website, or MISS when Instagram has no business or creator account
by that name. Compare the name and website with the festival: a handle
that exists is not always the festival's. Never prints the token.
"""
import json
import pathlib
import sys
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import watch_instagram as watch  # noqa: E402


def main(handles):
    token, user_id = watch.load_token(), watch.load_ig_user_id()
    if not token or not user_id:
        print("No Meta token or Instagram user id (see watch_instagram.py).", file=sys.stderr)
        return 2
    for handle in handles:
        if not watch.USERNAME_RE.fullmatch(handle):
            print(f"MISS {handle:28} not an Instagram username")
            continue
        fields = f"business_discovery.username({handle}){{username,name,followers_count,website}}"
        url = f"{watch.GRAPH}/{user_id}?" + urllib.parse.urlencode({"fields": fields, "access_token": token})
        request = urllib.request.Request(url, headers={"User-Agent": "encore-instagram-check"})
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                found = json.load(response)["business_discovery"]
            print(f"OK   {handle:28} {found.get('name', '')[:34]:34} "
                  f"{found.get('followers_count', 0):>10,}  {found.get('website') or ''}")
        except urllib.error.HTTPError as exc:
            try:
                message = json.loads(exc.read().decode() or "{}").get("error", {}).get("message", "")
            except json.JSONDecodeError:
                message = f"HTTP {exc.code}"
            print(f"MISS {handle:28} {watch.redact(message)[:70]}")
        except urllib.error.URLError as exc:
            print(f"MISS {handle:28} {watch.redact(str(exc.reason))[:70]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
