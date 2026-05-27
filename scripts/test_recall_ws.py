#!/usr/bin/env python3
"""
Recall.ai WS end-to-end test — cross-platform replacement for test_recall_ws.sh

Usage:
    python scripts/test_recall_ws.py "https://teams.live.com/meet/xxx?p=yyy"
"""
import asyncio
import json
import os
import re
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path


# ── Load .env ──────────────────────────────────────────────────────────────────
def load_env(path: Path) -> None:
    if not path.exists():
        sys.exit(f"❌  .env not found at {path}")
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r'^([^=]+)=(.*)', line)
        if m:
            key = m.group(1).strip()
            val = re.sub(r'\s+#.*$', '', m.group(2)).strip()
            os.environ.setdefault(key, val)


# ── Helpers ────────────────────────────────────────────────────────────────────
def require(key: str) -> str:
    val = os.environ.get(key, "").strip()
    if not val:
        sys.exit(f"❌  .env is missing {key}")
    return val


def get_ws_url() -> str:
    # Use RECALL_WS_PUBLIC_URL from .env (already the full wss:// URL)
    ws_url = os.environ.get("RECALL_WS_PUBLIC_URL", "").strip()
    if ws_url:
        return ws_url
    sys.exit(
        "❌  RECALL_WS_PUBLIC_URL is not set in .env\n"
        "    Set it to the WebSocket URL of your deployed bot, e.g.:\n"
        "    RECALL_WS_PUBLIC_URL=wss://your-app.azurecontainerapps.io/api/recall/ws"
    )


def recall_create_bot(base: str, api_key: str, meeting_url: str, ws_url: str) -> str:
    payload = {
        "meeting_url": meeting_url,
        "bot_name": "MOCHI-kiki-test",
        "recording_config": {
            "transcript": {
                "provider": {
                    "recallai_streaming": {
                        "language_code": "ja",
                        "mode": "prioritize_accuracy"
                    }
                }
            },
            "audio_mixed_raw": {},
            "realtime_endpoints": [
                {
                    "type": "websocket",
                    "url": ws_url,
                    "events": ["audio_mixed_raw.data", "transcript.data"]
                }
            ]
        }
    }
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{base}/api/v1/bot",
        data=data,
        headers={
            "Authorization": f"Token {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            body = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body_text = e.read().decode(errors="replace")
        try:
            body_text = json.dumps(json.loads(body_text), indent=2, ensure_ascii=False)
        except Exception:
            pass
        sys.exit(f"❌  Recall API error {e.code}:\n{body_text}")

    bot_id = body.get("id", "")
    if not bot_id:
        sys.exit(f"❌  No bot id in response:\n{json.dumps(body, indent=2, ensure_ascii=False)}")
    return bot_id


async def cosmos_upsert(endpoint: str, key: str, database: str, meeting_id: str, bot_id: str) -> None:
    from azure.cosmos.aio import CosmosClient
    client = CosmosClient(endpoint, credential=key)
    try:
        db = client.get_database_client(database)
        container = db.get_container_client("meetings")
        doc = {
            "id": meeting_id,
            "thread_id": "test-thread",
            "organizer_id": "test-organizer",
            "started_at": datetime.now(tz=timezone.utc).isoformat(),
            "ended_at": None,
            "transcript_subscription_id": None,
            "recall_bot_id": bot_id,
            "transcript_source": "recall",
        }
        await container.upsert_item(doc)
        print(f"✓  Cosmos upsert: id={meeting_id}  recall_bot_id={bot_id}")
    finally:
        await client.close()


# ── Main ───────────────────────────────────────────────────────────────────────
def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python scripts/test_recall_ws.py \"https://teams.live.com/meet/...\"")
        sys.exit(1)

    meeting_url = sys.argv[1]
    if not re.match(r'^https://teams\.(microsoft|live)\.com/', meeting_url):
        sys.exit("❌  URL must start with https://teams.microsoft.com/ or https://teams.live.com/")

    project_root = Path(__file__).parent.parent
    load_env(project_root / ".env")

    api_key        = require("RECALL_API_KEY")
    cosmos_ep      = require("AZURE_COSMOS_ENDPOINT")
    cosmos_key     = require("AZURE_COSMOS_KEY")
    cosmos_db      = os.environ.get("COSMOS_DATABASE", "meeting_db")
    recall_region  = os.environ.get("RECALL_REGION", "ap-northeast-1")
    app_name       = os.environ.get("APP_NAME", "mochikiki-bot-dev")
    rg_name        = os.environ.get("RG_NAME", "rg-mochi-kiki")

    recall_base = f"https://{recall_region}.recall.ai"
    ws_url      = get_ws_url()

    print()
    print("════════════════════════════════════════════════════════")
    print("Recall.ai WS E2E Test")
    print("════════════════════════════════════════════════════════")
    print(f"  Meeting URL  : {meeting_url}")
    print(f"  WS endpoint  : {ws_url}")
    print(f"  Recall region: {recall_region}  ({recall_base})")
    print(f"  Cosmos DB    : {cosmos_db}")
    print("════════════════════════════════════════════════════════")
    print()
    input("Send Recall.ai bot to the meeting? Press Enter to continue (Ctrl-C to cancel) ... ")

    # 1. Create bot
    print("::: 1. Creating Recall bot...")
    bot_id = recall_create_bot(recall_base, api_key, meeting_url, ws_url)
    print(f"✓  Bot ID: {bot_id}")

    # 2. Cosmos upsert
    meeting_id = f"test-{int(time.time())}"
    print(f"::: 2. Upserting Cosmos meetings record (id={meeting_id})...")
    try:
        asyncio.run(cosmos_upsert(cosmos_ep, cosmos_key, cosmos_db, meeting_id, bot_id))
    except Exception as e:
        print(f"⚠️  Cosmos upsert failed: {e}")
        print("   The bot WAS created. Recall retries for 90 sec — it may still connect.")

    print()
    print("════════════════════════════════════════════════════════")
    print("✅  Done — bot is joining the meeting")
    print("════════════════════════════════════════════════════════")
    print()
    print("▼ Admit the bot in Teams when the waiting room notification appears.")
    print()
    print("▼ Stream logs in another terminal:")
    print(f"    az containerapp logs show -n {app_name} -g {rg_name} --follow")
    print()
    print("▼ Stop the bot when done:")
    print(f"    python scripts/leave_bot.py {bot_id}")
    print()
    print(f"  BOT_ID          = {bot_id}")
    print(f"  TEST_MEETING_ID = {meeting_id}")


if __name__ == "__main__":
    main()
