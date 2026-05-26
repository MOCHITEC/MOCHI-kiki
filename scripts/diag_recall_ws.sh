#!/usr/bin/env bash
#
# Recall.ai WS 接続トラブル診断スクリプト。
# 「bot は会議にいるが Container App のログに WS 接続が出ない」状況の切り分け用。
#
# 使い方:
#   ./scripts/diag_recall_ws.sh <BOT_ID>
#
#   例:
#     ./scripts/diag_recall_ws.sh 72a2f54d-220f-4d01-8333-255cda51203f

set -uo pipefail

BOT_ID="${1:-}"
if [[ -z "$BOT_ID" ]]; then
  echo "Usage: $0 <BOT_ID>"
  exit 1
fi

cd "$(dirname "$0")/.."

if [[ ! -f .env ]]; then
  echo "❌ .env が見つからない"
  exit 1
fi

# .env から RECALL_API_KEY と RECALL_REGION を読む
set -a
# shellcheck disable=SC1091
source .env
set +a

RECALL_API_KEY="${RECALL_API_KEY:?.env に RECALL_API_KEY が必要}"
RECALL_REGION="${RECALL_REGION:-us-west-2}"
APP_NAME="${APP_NAME:-mochikiki-bot-dev}"
RG_NAME="${RG_NAME:-rg-mochi-kiki}"
RECALL_BASE="https://${RECALL_REGION}.recall.ai"

hr() { printf '═%.0s' {1..70}; echo; }

echo ""
hr
echo " Recall WS Diagnostics"
hr
echo "  Bot ID       : $BOT_ID"
echo "  Region       : $RECALL_REGION  ($RECALL_BASE)"
echo "  Container App: $APP_NAME / $RG_NAME"
hr

# ───────────────────────────────────────────────────────────
# [1/4] Container App ログから WS 関連を抽出
# ───────────────────────────────────────────────────────────
echo ""
hr
echo " [1/4] Container App logs — /api/recall/ws への HTTP リクエストを探す"
hr
LOGS="$(az containerapp logs show -n "$APP_NAME" -g "$RG_NAME" --tail 2000 2>&1 || true)"
echo "$LOGS" \
  | grep -E 'api/recall|" (101|401|404|500) |WS established|recall_ws_handler|meeting_id|svix-id|webhook-id|RecallWsHandler' \
  || echo "  (該当ログ無し)"

# ───────────────────────────────────────────────────────────
# [2/4] Bot の現在ステータス
# ───────────────────────────────────────────────────────────
echo ""
hr
echo " [2/4] Recall bot status_changes"
hr
RESP_BOT="$(curl -s -H "Authorization: Token $RECALL_API_KEY" \
  "$RECALL_BASE/api/v1/bot/${BOT_ID}/")"
echo "$RESP_BOT" | python3 - <<'PYEOF' 2>&1 || echo "$RESP_BOT"
import sys, json
try:
    d = json.load(sys.stdin)
except Exception as e:
    print(f"  JSON parse error: {e}")
    sys.exit(0)
print(f"  bot_name : {d.get('bot_name')}")
print(f"  join_at  : {d.get('join_at')}")
print(f"  status_changes:")
for s in d.get('status_changes', []):
    code = s.get('code', '')
    sub  = s.get('sub_code') or ''
    msg  = s.get('message') or ''
    print(f"    {s.get('created_at','')}  {code:30}  {sub}  {msg}")
print("")
print(f"  realtime_endpoints:")
for ep in d.get('recording_config', {}).get('realtime_endpoints', []):
    print(f"    type   : {ep.get('type')}")
    print(f"    url    : {ep.get('url')}")
    print(f"    events : {ep.get('events')}")
PYEOF

# ───────────────────────────────────────────────────────────
# [3/4] Recall 内部の realtime endpoint 接続状態
# ───────────────────────────────────────────────────────────
echo ""
hr
echo " [3/4] Recall realtime-endpoint 接続状態 (失敗回数・最終エラー等)"
hr
RESP_RTE="$(curl -s -H "Authorization: Token $RECALL_API_KEY" \
  "$RECALL_BASE/api/v1/realtime-endpoint/?bot_id=${BOT_ID}")"
echo "$RESP_RTE" | python3 -m json.tool 2>&1 || echo "$RESP_RTE"

# ───────────────────────────────────────────────────────────
# [4/4] Recall bot ログ (もし API がある場合)
# ───────────────────────────────────────────────────────────
echo ""
hr
echo " [4/4] Recall bot logs API"
hr
RESP_LOGS="$(curl -s -H "Authorization: Token $RECALL_API_KEY" \
  "$RECALL_BASE/api/v1/bot/${BOT_ID}/logs/")"
echo "$RESP_LOGS" | python3 -m json.tool 2>&1 | head -200 || echo "$RESP_LOGS" | head -200

# ───────────────────────────────────────────────────────────
# [5/5] WS endpoint への直接到達性 (curl Upgrade で 401 期待)
# ───────────────────────────────────────────────────────────
echo ""
hr
echo " [5/5] WS endpoint への直接到達性 (期待 status=401)"
hr
FQDN="$(az containerapp show -n "$APP_NAME" -g "$RG_NAME" \
  --query properties.configuration.ingress.fqdn -o tsv 2>/dev/null || echo "")"
if [[ -n "$FQDN" ]]; then
  HTTPS_URL="https://${FQDN}/api/recall/ws"
  STATUS="$(curl -s -o /dev/null -w '%{http_code}' \
    -H 'Connection: Upgrade' \
    -H 'Upgrade: websocket' \
    -H 'Sec-WebSocket-Version: 13' \
    -H 'Sec-WebSocket-Key: dGVzdHRlc3R0ZXN0dGVzdA==' \
    "$HTTPS_URL")"
  echo "  GET $HTTPS_URL  → status=$STATUS"
  if [[ "$STATUS" == "401" ]]; then
    echo "  ✅ WS endpoint は配線されている（認証無しなので 401 が正解）"
  else
    echo "  ⚠️  期待値 401 と異なる。要確認"
  fi
else
  echo "  FQDN 取得失敗"
fi

echo ""
hr
echo "診断完了"
hr
