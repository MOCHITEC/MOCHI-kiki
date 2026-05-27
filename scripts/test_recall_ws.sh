#!/usr/bin/env bash
#
# Recall.ai WS 経路の end-to-end テスト用スクリプト。
#
# 何をするか:
#   1. .env から RECALL_API_KEY / Cosmos 接続情報を読む
#   2. Container App の FQDN を取得
#   3. Recall.ai bot を curl で投入（WS endpoint 指定）
#   4. レスポンスから bot_id を取得し、Cosmos meetings コンテナに
#      meeting_id ↔ recall_bot_id の対応レコードを upsert
#   5. ログ tail コマンドと bot 終了コマンドを表示
#
# 使い方:
#   ./scripts/test_recall_ws.sh "<TEAMS_MEETING_URL>"
#
# 例:
#   ./scripts/test_recall_ws.sh "https://teams.microsoft.com/l/meetup-join/xxx"

set -euo pipefail

MEETING_URL="${1:-}"
if [[ -z "$MEETING_URL" ]]; then
  echo "Usage: $0 <TEAMS_MEETING_URL>"
  echo "  例: $0 \"https://teams.microsoft.com/l/meetup-join/...\""
  exit 1
fi

if [[ ! "$MEETING_URL" =~ ^https://teams\.(microsoft|live)\.com/ ]]; then
  echo "❌ MEETING_URL は https://teams.microsoft.com/ もしくは https://teams.live.com/ で始まること"
  exit 1
fi

cd "$(dirname "$0")/.."

if [[ ! -f .env ]]; then
  echo "❌ .env が無い。fetch_azure_env.sh で生成してください"
  exit 1
fi

# .env 読込
set -a
# shellcheck disable=SC1091
source .env
set +a

: "${RECALL_API_KEY:?.env に RECALL_API_KEY が必要}"
: "${AZURE_COSMOS_ENDPOINT:?.env に AZURE_COSMOS_ENDPOINT が必要}"
: "${AZURE_COSMOS_KEY:?.env に AZURE_COSMOS_KEY が必要}"
COSMOS_DATABASE="${COSMOS_DATABASE:-meeting_db}"
RECALL_REGION="${RECALL_REGION:-ap-northeast-1}"

RG_NAME="${RG_NAME:-rg-mochi-kiki}"
APP_NAME="${APP_NAME:-mochikiki-bot-dev}"

command -v az >/dev/null      || { echo "az cli が必要"; exit 1; }
command -v python3 >/dev/null || { echo "python3 が必要"; exit 1; }
command -v jq >/dev/null      || { echo "jq が必要 (brew install jq)"; exit 1; }

FQDN="$(az containerapp show -n "$APP_NAME" -g "$RG_NAME" \
  --query properties.configuration.ingress.fqdn -o tsv)"
WS_URL="wss://${FQDN}/api/recall/ws"

RECALL_BASE="https://${RECALL_REGION}.recall.ai"

echo "════════════════════════════════════════════════════════"
echo "Recall.ai WS E2E テスト"
echo "════════════════════════════════════════════════════════"
echo "  Meeting URL  : $MEETING_URL"
echo "  WS endpoint  : $WS_URL"
echo "  Recall region: $RECALL_REGION  ($RECALL_BASE)"
echo "  Cosmos DB    : $COSMOS_DATABASE"
echo "════════════════════════════════════════════════════════"
echo ""

read -r -p "Recall.ai bot を投入します。よければ Enter / 中止は Ctrl-C ... " _

# ── 1) Recall.ai bot を投入 ──────────────────────────────────
echo "::: 1. Recall bot を投入中..."

RESP="$(curl -sS -X POST "$RECALL_BASE/api/v1/bot" \
  -H "Authorization: Token $RECALL_API_KEY" \
  -H "Content-Type: application/json" \
  -d @- <<JSON
{
  "meeting_url": "$MEETING_URL",
  "bot_name": "MOCHI-kiki-test",
  "recording_config": {
    "transcript": {
      "provider": {"recallai_streaming": {"language_code": "ja", "mode": "prioritize_low_latency"}}
    },
    "audio_mixed_raw": {},
    "realtime_endpoints": [
      {
        "type": "websocket",
        "url": "$WS_URL",
        "events": ["audio_mixed_raw.data", "transcript.data"]
      }
    ]
  }
}
JSON
)"

BOT_ID="$(echo "$RESP" | jq -r '.id // empty')"
if [[ -z "$BOT_ID" ]]; then
  echo "❌ bot 投入失敗。レスポンス:"
  echo "$RESP" | jq . || echo "$RESP"
  exit 1
fi
echo "✓ Bot ID: $BOT_ID"

# ── 2) Cosmos に meetings レコードを upsert ─────────────────
TEST_MEETING_ID="test-$(date +%s)"
echo "::: 2. Cosmos meetings レコードを作成 (id=$TEST_MEETING_ID)"

export _MEETING_ID="$TEST_MEETING_ID"
export _BOT_ID="$BOT_ID"

python3 - <<'PYEOF'
import asyncio
import os
from datetime import datetime, timezone
from azure.cosmos.aio import CosmosClient

async def main():
    endpoint = os.environ["AZURE_COSMOS_ENDPOINT"]
    key      = os.environ["AZURE_COSMOS_KEY"]
    db_name  = os.environ.get("COSMOS_DATABASE", "meeting_db")
    meeting_id = os.environ["_MEETING_ID"]
    bot_id     = os.environ["_BOT_ID"]

    client = CosmosClient(endpoint, credential=key)
    db = client.get_database_client(db_name)
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
    print(f"✓ Upserted meeting doc: id={meeting_id} recall_bot_id={bot_id}")
    await client.close()

asyncio.run(main())
PYEOF

echo ""
echo "════════════════════════════════════════════════════════"
echo "✅ セットアップ完了"
echo "════════════════════════════════════════════════════════"
echo ""
echo "▼ ログを別ターミナルで tail してください:"
echo "    az containerapp logs show -n $APP_NAME -g $RG_NAME --follow"
echo ""
echo "▼ 期待するログ:"
echo "    RecallWsHandler: WS established remote=..."
echo "    （会議で発話すると以下が流れる）"
echo "    [発話受信] ..."
echo ""
echo "▼ テスト終了時は bot を退出させてください:"
echo "    curl -X POST $RECALL_BASE/api/v1/bot/$BOT_ID/leave_call/ \\"
echo "      -H 'Authorization: Token \$RECALL_API_KEY'"
echo ""
echo "保存しておくと便利な値:"
echo "    BOT_ID=$BOT_ID"
echo "    TEST_MEETING_ID=$TEST_MEETING_ID"
