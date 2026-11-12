#!/usr/bin/env python3
"""Vendor the JSON Schemas of every released UCP version into
agentready/schemas/ucp/<version>/ (all JSON files under the repo's source/).

Run by .github/workflows/sync-ucp.yml weekly; opens a PR when a new
release appears. Usage:  python scripts/sync_ucp_schemas.py [--only 2026-08-25]
"""
from __future__ import annotations

import argparse
import io
import json
import re
import shutil
import subprocess
import sys
import tarfile
import urllib.request
from pathlib import Path

REPO = "Universal-Commerce-Protocol/ucp"
DEST = Path(__file__).resolve().parent.parent / "agentready" / "schemas" / "ucp"


def release_versions() -> list[str]:
    """Release tags look like v2026-08-25. git ls-remote avoids API rate limits."""
    try:
        out = subprocess.run(["git", "ls-remote", "--tags", f"https://github.com/{REPO}.git"],
                             capture_output=True, text=True, check=True).stdout
        tags = [line.split("refs/tags/")[1] for line in out.splitlines() if "refs/tags/" in line]
    except (OSError, subprocess.CalledProcessError):
        url = f"https://api.github.com/repos/{REPO}/tags?per_page=100"
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "agentready"})) as r:
            tags = [t["name"] for t in json.load(r)]
    return sorted({t[1:] for t in tags if re.fullmatch(r"v\d{4}-\d{2}-\d{2}", t)})


def vendor(version: str) -> int:
    url = f"https://codeload.github.com/{REPO}/tar.gz/refs/tags/v{version}"
    with urllib.request.urlopen(url) as r:
        data = r.read()
    out = DEST / version
    if out.exists():
        shutil.rmtree(out)
    count = 0
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        for m in tar.getmembers():
            parts = m.name.split("/")
            if not m.isfile() or len(parts) < 3 or parts[1] != "source" or not m.name.endswith(".json"):
                continue
            rel = Path(*parts[2:])
            target = out / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(tar.extractfile(m).read())
            count += 1
    return count


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="vendor a single version, e.g. 2026-08-25")
    args = ap.parse_args()
    versions = [args.only] if args.only else release_versions()
    DEST.mkdir(parents=True, exist_ok=True)
    for v in versions:
        print(f"UCP {v}: {vendor(v)} schema files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
