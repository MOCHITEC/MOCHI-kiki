#!/usr/bin/env bash
#
# Azure リソースから .env の値を取得して標準出力に書き出す。
# 使い方:
#   ./scripts/fetch_azure_env.sh           標準出力に表示
#   ./scripts/fetch_azure_env.sh > .env    .env を上書き保存
#   ./scripts/fetch_azure_env.sh >> .env   .env に追記
#
# 環境変数:
#   RG_NAME   リソースグループ (default: rg-mochi-kiki)
#   APP_NAME  Container App   (default: mochikiki-bot-dev)
#
# 取得しない値（手動入力必須）:
#   MICROSOFT_APP_ID / _PASSWORD  Bot Framework App registration
#   GRAPH_CLIENT_ID / _SECRET     Graph 用 Service Principal
#   RECALL_API_KEY                Recall.ai dashboard
#   RECALL_WEBHOOK_SECRET         Recall.ai dashboard (Verification Secret)

set -euo pipefail

RG_NAME="${RG_NAME:-rg-mochi-kiki}"
APP_NAME="${APP_NAME:-mochikiki-bot-dev}"

command -v az >/dev/null || { echo "az cli が必要" >&2; exit 1; }
az account show -o none 2>/dev/null || { echo "az login が必要" >&2; exit 1; }

err() { echo "::: $*" >&2; }

err "リソース一覧を取得 ($RG_NAME)"

COSMOS_NAME="$(az cosmosdb list -g "$RG_NAME" --query "[0].name" -o tsv 2>/dev/null || true)"
OPENAI_NAME="$(az cognitiveservices account list -g "$RG_NAME" --query "[?kind=='OpenAI'] | [0].name" -o tsv 2>/dev/null || true)"
SEARCH_NAME="$(az search service list -g "$RG_NAME" --query "[0].name" -o tsv 2>/dev/null || true)"

[[ -n "$COSMOS_NAME" ]] || { echo "Cosmos DB が $RG_NAME に見つからない" >&2; exit 1; }
[[ -n "$OPENAI_NAME" ]] || { echo "Azure OpenAI が $RG_NAME に見つからない" >&2; exit 1; }
[[ -n "$SEARCH_NAME" ]] || { echo "Azure AI Search が $RG_NAME に見つからない" >&2; exit 1; }

err "Cosmos:   $COSMOS_NAME"
err "OpenAI:   $OPENAI_NAME"
err "Search:   $SEARCH_NAME"
err "App:      $APP_NAME"

err "endpoint / key を取得中..."

COSMOS_ENDPOINT="$(az cosmosdb show -n "$COSMOS_NAME" -g "$RG_NAME" --query documentEndpoint -o tsv)"
COSMOS_KEY="$(az cosmosdb keys list -n "$COSMOS_NAME" -g "$RG_NAME" --query primaryMasterKey -o tsv)"

OPENAI_ENDPOINT="$(az cognitiveservices account show -n "$OPENAI_NAME" -g "$RG_NAME" --query properties.endpoint -o tsv)"
OPENAI_KEY="$(az cognitiveservices account keys list -n "$OPENAI_NAME" -g "$RG_NAME" --query key1 -o tsv)"

SEARCH_ENDPOINT="https://${SEARCH_NAME}.search.windows.net"
SEARCH_KEY="$(az search admin-key show --service-name "$SEARCH_NAME" -g "$RG_NAME" --query primaryKey -o tsv)"

FQDN="$(az containerapp show -n "$APP_NAME" -g "$RG_NAME" --query properties.latestRevisionFqdn -o tsv)"
TENANT_ID="$(az account show --query tenantId -o tsv)"

err "完了。 stdout に出力します。"

cat <<EOF
# Auto-fetched from Azure $(date '+%Y-%m-%d %H:%M:%S')
# RG=$RG_NAME  Cosmos=$COSMOS_NAME  OpenAI=$OPENAI_NAME  Search=$SEARCH_NAME

# Bot Framework  (★ 手動入力必須: Azure Portal -> Microsoft Entra -> App registrations)
MICROSOFT_APP_ID=
MICROSOFT_APP_PASSWORD=

# Azure Cosmos DB
AZURE_COSMOS_ENDPOINT=$COSMOS_ENDPOINT
AZURE_COSMOS_KEY=$COSMOS_KEY
COSMOS_DATABASE=meeting_db

# Microsoft Graph API
GRAPH_TENANT_ID=$TENANT_ID
GRAPH_CLIENT_ID=                            # ★ 手動: Graph 用 SP (Bot とは別の場合あり)
GRAPH_CLIENT_SECRET=                        # ★ 手動
GRAPH_NOTIFICATION_URL=https://$FQDN/api/notifications

# App
PORT=3978

# Azure OpenAI
AZURE_OPENAI_ENDPOINT=$OPENAI_ENDPOINT
AZURE_OPENAI_KEY=$OPENAI_KEY
AZURE_OPENAI_DEPLOYMENT=gpt-4o
AZURE_OPENAI_EMBEDDING_DEPLOYMENT=text-embedding-3-small

# Azure AI Search
AZURE_SEARCH_ENDPOINT=$SEARCH_ENDPOINT
AZURE_SEARCH_KEY=$SEARCH_KEY
AZURE_SEARCH_INDEX=documents

# Recall.ai  (RECALL_API_KEY / RECALL_WEBHOOK_SECRET は dashboard -> API Keys)
TRANSCRIPT_SOURCE=recall                    # graph | recall | both
RECALL_API_KEY=                             # ★ 手動
RECALL_WEBHOOK_SECRET=                      # ★ 手動 (whsec_...)
RECALL_REGION=us-east-1
RECALL_TRANSPORT=websocket                  # webhook | websocket | both
RECALL_WS_PUBLIC_URL=wss://$FQDN/api/recall/ws
RECALL_WEBHOOK_PUBLIC_URL=https://$FQDN/api/recall/webhook
RECALL_AUDIO_SINK=noop                      # noop | file | azure_speech
EOF
