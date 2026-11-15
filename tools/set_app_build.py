#!/usr/bin/env python3
"""Tell the apps which build testers can install now (Nov 14, 2026).

    tools/set_app_build.py ios 95
    tools/set_app_build.py android 70 [--url https://...]

Sets meta.iosBuild / meta.androidBuild (and the matching update link) in
v2/config.json and bumps meta.version and meta.publishedAt. An app on an
older build shows "A newer Encore is ready" on Home. Run it when a build
has actually reached the testers (TestFlight's Friends group, Play
internal testing), not when it was started: a prompt for a build nobody
can install yet sends people nowhere. Then commit and push; that
publishes.

The file is edited as text so the diff is only these lines.
"""

import datetime
import re
import sys

PATH = "v2/config.json"
LINKS = {
    "ios": "https://testflight.apple.com/join/q9egDUzC",
    "android": "https://play.google.com/apps/internaltest/4699840607140778833",
}


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) != 2 or args[0] not in LINKS or not args[1].isdigit():
        print(__doc__, file=sys.stderr)
        return 2
    platform, build = args[0], int(args[1])
    url = LINKS[platform]
    if "--url" in sys.argv:
        url = sys.argv[sys.argv.index("--url") + 1]
    text = open(PATH, encoding="utf-8").read()
    head_end = text.index("}", text.index('"meta"'))
    head = text[:head_end]
    version = int(re.search(r'"version": (\d+)', head).group(1))
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    fields = dict(re.findall(r'"(\w+)": ("[^"]*"|\d+)', head[head.index('"meta"'):]))
    fields["version"] = str(version + 1)
    fields["publishedAt"] = f'"{now}"'
    fields[f"{platform}Build"] = str(build)
    fields[f"{platform}UpdateUrl"] = f'"{url}"'
    order = ["version", "publishedAt", "iosBuild", "iosUpdateUrl", "androidBuild", "androidUpdateUrl"]
    keys = [k for k in order if k in fields] + sorted(k for k in fields if k not in order)
    body = ",\n".join(f'    "{k}": {fields[k]}' for k in keys)
    start = text.index("{", text.index('"meta"'))
    text = text[:start] + "{\n" + body + "\n  " + text[head_end:]
    open(PATH, "w", encoding="utf-8").write(text)
    print(f"{platform} build {build}; catalog version {version + 1}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
