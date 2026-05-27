#!/usr/bin/env python3
"""Stop a Recall.ai bot.

Usage:
    python scripts/leave_bot.py <BOT_ID>
"""
import os
import re
import sys
import urllib.request
import urllib.error
from pathlib import Path


def load_env(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r'^([^=]+)=(.*)', line)
        if m:
            key = m.group(1).strip()
            val = re.sub(r'\s+#.*$', '', m.group(2)).strip()
            os.environ.setdefault(key, val)


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python scripts/leave_bot.py <BOT_ID>")
        sys.exit(1)

    bot_id = sys.argv[1]
    load_env(Path(__file__).parent.parent / ".env")

    api_key = os.environ.get("RECALL_API_KEY", "").strip()
    region  = os.environ.get("RECALL_REGION", "ap-northeast-1").strip()
    if not api_key:
        sys.exit("ERROR: RECALL_API_KEY not set in .env")

    url = f"https://{region}.recall.ai/api/v1/bot/{bot_id}/leave_call/"
    req = urllib.request.Request(
        url,
        data=b"",
        headers={"Authorization": f"Token {api_key}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            print(f"[OK] Bot {bot_id} told to leave (HTTP {resp.status})")
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        if e.code == 400:
            print(f"[INFO] HTTP 400 -- bot {bot_id} has already left or ended.")
        else:
            print(f"[ERROR] HTTP {e.code}: {body}")
            sys.exit(1)


if __name__ == "__main__":
    main()
