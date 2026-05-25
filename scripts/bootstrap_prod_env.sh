#!/usr/bin/env bash
#
# 本番 Container App に必要な env / secret をローカル .env から一括投入する。
# Recall.ai 関連は対話的に入力させる。
#
# 注意:
#   - これはスケルトン状態の Container App を初めて本番稼働させるための bootstrap
#   - 既存値があれば上書きする（CAUTION）
#   - 一度だけ動かせば良い。WS 切替のときは deploy_recall_ws.sh を使う
#
# 使い方:
#   ./scripts/bootstrap_prod_env.sh            通常実行
#   DRY_RUN=1 ./scripts/bootstrap_prod_env.sh  echo のみ

set -euo pipefail

RG_NAME="${RG_NAME:-rg-mochi-kiki}"
APP_NAME="${APP_NAME:-mochikiki-bot-dev}"
DRY_RUN="${DRY_RUN:-0}"

cd "$(dirname "$0")/.."

if [[ ! -f .env ]]; then
  echo "❌ .env がプロジェクトルートに無い"
  exit 1
fi

run() {
  if [[ "$DRY_RUN" == "1" ]]; then
    # 引数中の秘密値を遮蔽してから echo
    local masked=()
    for a in "$@"; do
      case "$a" in
        *=secretref:*) masked+=("$a") ;;          # secret ref はそのまま
        # key=value 形式かつ value が秘密っぽい name のときは伏せる
        ms-app-id=*|ms-app-password=*|cosmos-key=*|graph-client-secret=*|openai-key=*|search-key=*|recall-api-key=*|recall-webhook-secret=*|recall-ws-public-url=*)
          masked+=("${a%%=*}=<REDACTED>") ;;
        # env 名が機密ならマスク
        MICROSOFT_APP_*=*|AZURE_COSMOS_KEY=*|GRAPH_CLIENT_SECRET=*|AZURE_OPENAI_KEY=*|AZURE_SEARCH_KEY=*|RECALL_API_KEY=*|RECALL_WEBHOOK_SECRET=*)
          masked+=("${a%%=*}=<REDACTED>") ;;
        *) masked+=("$a") ;;
      esac
    done
    echo "+ ${masked[*]}"
  else
    "$@"
  fi
}

# .env を読み込む（コメントと空行をスキップ）
set -a
# shellcheck disable=SC1091
source .env
set +a

# 必須チェック
required=(MICROSOFT_APP_ID MICROSOFT_APP_PASSWORD AZURE_COSMOS_ENDPOINT AZURE_COSMOS_KEY \
          GRAPH_TENANT_ID GRAPH_CLIENT_ID GRAPH_CLIENT_SECRET GRAPH_NOTIFICATION_URL \
          AZURE_OPENAI_ENDPOINT AZURE_OPENAI_KEY \
          AZURE_SEARCH_ENDPOINT AZURE_SEARCH_KEY)
missing=()
for v in "${required[@]}"; do
  if [[ -z "${!v:-}" ]]; then
    missing+=("$v")
  fi
done
if [[ ${#missing[@]} -gt 0 ]]; then
  echo "❌ .env に値が無い: ${missing[*]}"
  exit 1
fi

# Container App の現 FQDN を取得（GRAPH_NOTIFICATION_URL の整合確認用）
FQDN="$(az containerapp show -n "$APP_NAME" -g "$RG_NAME" \
        --query properties.latestRevisionFqdn -o tsv)"
echo "Current FQDN: $FQDN"
echo ""

# Recall.ai 関連を対話で取得
echo "── Recall.ai credentials を入力（既に取得済みなら貼り付け） ──"
if [[ -z "${RECALL_API_KEY:-}" ]]; then
  read -r -p "  RECALL_API_KEY: " RECALL_API_KEY
fi
if [[ -z "${RECALL_WEBHOOK_SECRET:-}" ]]; then
  read -r -p "  RECALL_WEBHOOK_SECRET (whsec_...): " RECALL_WEBHOOK_SECRET
fi
RECALL_REGION="${RECALL_REGION:-us-east-1}"

# WS 経路をデフォルトの推奨値とする。deploy_recall_ws.sh と整合。
RECALL_TRANSPORT="${RECALL_TRANSPORT:-websocket}"
RECALL_WS_PUBLIC_URL="${RECALL_WS_PUBLIC_URL:-wss://${FQDN}/api/recall/ws}"
RECALL_WEBHOOK_PUBLIC_URL="${RECALL_WEBHOOK_PUBLIC_URL:-https://${FQDN}/api/recall/webhook}"
TRANSCRIPT_SOURCE="${TRANSCRIPT_SOURCE:-recall}"

echo ""
echo "── 設定予定 ──"
echo "  TRANSCRIPT_SOURCE         = $TRANSCRIPT_SOURCE"
echo "  RECALL_TRANSPORT          = $RECALL_TRANSPORT"
echo "  RECALL_WS_PUBLIC_URL      = $RECALL_WS_PUBLIC_URL"
echo "  RECALL_WEBHOOK_PUBLIC_URL = $RECALL_WEBHOOK_PUBLIC_URL"
echo "  RECALL_REGION             = $RECALL_REGION"
echo "  GRAPH_NOTIFICATION_URL    = $GRAPH_NOTIFICATION_URL"
echo "  (bot 名 / 言語 / WS event は src/main.py でハードコード)"
echo "  (シークレット類は値を非表示)"
echo ""
if [[ "$DRY_RUN" != "1" ]]; then
  read -r -p "進めて良ければ yes: " ans
  [[ "$ans" == "yes" ]] || { echo "中止"; exit 1; }
fi

# ── 1. Container App secret に登録 ──────────────────────────
echo "::: 1. secret 登録"
run az containerapp secret set \
  --name "$APP_NAME" --resource-group "$RG_NAME" \
  --secrets \
    "ms-app-id=${MICROSOFT_APP_ID}" \
    "ms-app-password=${MICROSOFT_APP_PASSWORD}" \
    "cosmos-key=${AZURE_COSMOS_KEY}" \
    "graph-client-secret=${GRAPH_CLIENT_SECRET}" \
    "openai-key=${AZURE_OPENAI_KEY}" \
    "search-key=${AZURE_SEARCH_KEY}" \
    "recall-api-key=${RECALL_API_KEY}" \
    "recall-webhook-secret=${RECALL_WEBHOOK_SECRET}"

# ── 2. env 一括設定（既存 PORT / AZURE_KEYVAULT_URI は維持される） ─
echo "::: 2. env 設定"
run az containerapp update \
  --name "$APP_NAME" --resource-group "$RG_NAME" \
  --set-env-vars \
    "MICROSOFT_APP_ID=secretref:ms-app-id" \
    "MICROSOFT_APP_PASSWORD=secretref:ms-app-password" \
    "AZURE_COSMOS_ENDPOINT=${AZURE_COSMOS_ENDPOINT}" \
    "AZURE_COSMOS_KEY=secretref:cosmos-key" \
    "COSMOS_DATABASE=${COSMOS_DATABASE:-meeting_db}" \
    "GRAPH_TENANT_ID=${GRAPH_TENANT_ID}" \
    "GRAPH_CLIENT_ID=${GRAPH_CLIENT_ID}" \
    "GRAPH_CLIENT_SECRET=secretref:graph-client-secret" \
    "GRAPH_NOTIFICATION_URL=${GRAPH_NOTIFICATION_URL}" \
    "AZURE_OPENAI_ENDPOINT=${AZURE_OPENAI_ENDPOINT}" \
    "AZURE_OPENAI_KEY=secretref:openai-key" \
    "AZURE_OPENAI_DEPLOYMENT=${AZURE_OPENAI_DEPLOYMENT:-gpt-4o}" \
    "AZURE_OPENAI_EMBEDDING_DEPLOYMENT=${AZURE_OPENAI_EMBEDDING_DEPLOYMENT:-text-embedding-3-small}" \
    "AZURE_SEARCH_ENDPOINT=${AZURE_SEARCH_ENDPOINT}" \
    "AZURE_SEARCH_KEY=secretref:search-key" \
    "AZURE_SEARCH_INDEX=${AZURE_SEARCH_INDEX:-documents}" \
    "TRANSCRIPT_SOURCE=${TRANSCRIPT_SOURCE}" \
    "RECALL_API_KEY=secretref:recall-api-key" \
    "RECALL_WEBHOOK_SECRET=secretref:recall-webhook-secret" \
    "RECALL_REGION=${RECALL_REGION}" \
    "RECALL_TRANSPORT=${RECALL_TRANSPORT}" \
    "RECALL_WEBHOOK_PUBLIC_URL=${RECALL_WEBHOOK_PUBLIC_URL}" \
    "RECALL_WS_PUBLIC_URL=${RECALL_WS_PUBLIC_URL}" \
    "RECALL_AUDIO_SINK=noop"

echo ""
echo "✅ env / secret 投入完了。次は image を最新コードでビルド & push:"
echo "   ./scripts/deploy_recall_ws.sh"
echo ""
echo "ヒント: bootstrap デフォルトは RECALL_TRANSPORT=websocket (生音声 + transcript)。"
echo "       webhook も併用したい移行期は: RECALL_TRANSPORT=both ./scripts/bootstrap_prod_env.sh"
