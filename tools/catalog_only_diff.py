#!/usr/bin/env python3
"""Is a branch only enriching the catalog? (Ezra, Nov 27, 2026)

The requests routine merges its own pull request when this says yes, and
leaves it for Ezra when it says no. Yes means, against the base branch:

- the only files changed are v2/config.json, requests/handled.json and
  requests/log.md;
- v2/config.json only gains festivals: every festival already on the base
  is byte-for-byte the same and still there, `shows` and `artists` are
  unchanged, and `meta` changes only `version` and `publishedAt`
  (`requestOutcomes` may change freely).

Usage:
    python3 tools/catalog_only_diff.py [base-ref] [head-ref]

Defaults: origin/main and HEAD. Exit 0 and "catalog-only" when the change
qualifies; exit 1 with one reason per line when it doesn't.
"""

import json
import subprocess
import sys

ALLOWED_FILES = {"v2/config.json", "requests/handled.json", "requests/log.md"}
META_ALLOWED = {"version", "publishedAt"}


def git(*args):
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True).stdout


def config_at(ref):
    return json.loads(git("show", f"{ref}:v2/config.json"))


def main():
    base = sys.argv[1] if len(sys.argv) > 1 else "origin/main"
    head = sys.argv[2] if len(sys.argv) > 2 else "HEAD"
    reasons = []

    merge_base = git("merge-base", base, head).strip()
    changed = set(filter(None, git("diff", "--name-only", merge_base, head).splitlines()))
    for path in sorted(changed - ALLOWED_FILES):
        reasons.append(f"changes {path}")

    old, new = config_at(merge_base), config_at(head)
    for key in sorted(set(old) | set(new)):
        if key in ("festivals", "requestOutcomes", "meta"):
            continue
        if old.get(key) != new.get(key):
            reasons.append(f"changes top-level {key!r}")

    old_meta, new_meta = old.get("meta", {}), new.get("meta", {})
    for key in sorted(set(old_meta) | set(new_meta)):
        if key not in META_ALLOWED and old_meta.get(key) != new_meta.get(key):
            reasons.append(f"changes meta.{key}")

    new_by_id = {f.get("id"): f for f in new.get("festivals", [])}
    for f in old.get("festivals", []):
        fid = f.get("id")
        if fid not in new_by_id:
            reasons.append(f"removes festival {fid}")
        elif new_by_id[fid] != f:
            reasons.append(f"edits existing festival {fid}")

    if reasons:
        print("\n".join(reasons))
        return 1
    added = sorted(set(new_by_id) - {f.get("id") for f in old.get("festivals", [])})
    print("catalog-only" + (f": adds {', '.join(added)}" if added else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
