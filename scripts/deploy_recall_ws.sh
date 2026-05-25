#!/usr/bin/env bash
#
# Recall.ai WebSocket 経路をデプロイするスクリプト。
#
# 前提:
#   - 既に terraform apply 済の Container App / Key Vault / ACR が存在する
#   - az cli にログイン済 (`az login`)
#   - docker / 適切な platform イメージビルド環境
#
# 実行内容:
#   1) terraform apply（ingress.transport=http 反映、recall_ws_url 出力追加）
#   2) Docker イメージビルド & ACR push（linux/amd64）
#   3) Container App に WS 関連 env を追加
#   4) Container App のイメージ更新（新リビジョン作成）
#   5) smoke test: /api/recall/ws に Upgrade して 401 を確認
#
# 環境変数で挙動を制御:
#   RG_NAME           リソースグループ名 (default: rg-mochi-kiki)
#   APP_NAME          Container App 名 (default: mochikiki-bot-dev)
#   ACR_NAME          ACR 名 (default: mochikikiacrdev)
#   IMAGE_TAG         タグ (default: ws-$(date +%Y%m%d-%H%M%S))
#   RECALL_TRANSPORT  webhook | websocket | both (default: both)
#   RECALL_AUDIO_SINK noop | file | azure_speech (default: noop)
#   SKIP_TF           1 で terraform apply をスキップ
#   SKIP_BUILD        1 でビルド & push をスキップ
#   SKIP_DEPLOY       1 で az containerapp update をスキップ
#   DRY_RUN           1 で各コマンドを echo するだけ

set -euo pipefail

# ── デフォルト ────────────────────────────────────────────────
RG_NAME="${RG_NAME:-rg-mochi-kiki}"
APP_NAME="${APP_NAME:-mochikiki-bot-dev}"
ACR_NAME="${ACR_NAME:-mochikikiacrdev}"
IMAGE_NAME="mochi-kiki-bot"
IMAGE_TAG="${IMAGE_TAG:-ws-$(date +%Y%m%d-%H%M%S)}"
RECALL_TRANSPORT="${RECALL_TRANSPORT:-both}"
RECALL_AUDIO_SINK="${RECALL_AUDIO_SINK:-noop}"
SKIP_TF="${SKIP_TF:-0}"
SKIP_BUILD="${SKIP_BUILD:-0}"
SKIP_DEPLOY="${SKIP_DEPLOY:-0}"
DRY_RUN="${DRY_RUN:-0}"

run() {
  if [[ "$DRY_RUN" == "1" ]]; then
    echo "+ $*"
  else
    echo "+ $*" >&2
    "$@"
  fi
}

cd "$(dirname "$0")/.."

# ── 0. 前提確認 ──────────────────────────────────────────────
command -v az >/dev/null || { echo "az cli が必要"; exit 1; }
command -v docker >/dev/null || { echo "docker が必要"; exit 1; }
if [[ "$SKIP_TF" != "1" ]]; then
  command -v terraform >/dev/null || { echo "terraform が必要"; exit 1; }
fi

if ! az account show -o none 2>/dev/null; then
  echo "az login が必要"
  exit 1
fi

# ── 0-b. 既存 env 事前チェック (壊さないため) ─────────────────
echo "::: 0-b. 既存 Container App env を確認"
EXISTING_ENV_JSON="$(az containerapp show \
  --name "$APP_NAME" --resource-group "$RG_NAME" \
  --query "properties.template.containers[0].env" -o json 2>/dev/null || echo '[]')"

if [[ "$EXISTING_ENV_JSON" == "[]" || -z "$EXISTING_ENV_JSON" ]]; then
  echo "❌ Container App $APP_NAME が見つからない、または env が空です。"
  echo "    先に他の方の初期デプロイが完了しているか確認してください。"
  exit 1
fi

# 必須 env が prod に存在することを確認する関数
check_env() {
  local name="$1"
  if ! echo "$EXISTING_ENV_JSON" | grep -q "\"name\": \"$name\""; then
    echo "  ⚠️  $name が prod に未設定"
    MISSING_ENVS+=("$name")
  else
    echo "  ✓ $name"
  fi
}

MISSING_ENVS=()
echo "必須 env チェック:"
check_env "MICROSOFT_APP_ID"
check_env "MICROSOFT_APP_PASSWORD"
check_env "AZURE_COSMOS_ENDPOINT"
check_env "AZURE_COSMOS_KEY"
check_env "GRAPH_TENANT_ID"
check_env "GRAPH_CLIENT_ID"
check_env "GRAPH_CLIENT_SECRET"
check_env "GRAPH_NOTIFICATION_URL"
check_env "AZURE_OPENAI_ENDPOINT"
check_env "AZURE_OPENAI_KEY"
check_env "AZURE_SEARCH_ENDPOINT"
check_env "AZURE_SEARCH_KEY"
check_env "RECALL_API_KEY"
check_env "RECALL_WEBHOOK_SECRET"
check_env "TRANSCRIPT_SOURCE"

if [[ ${#MISSING_ENVS[@]} -gt 0 ]]; then
  echo ""
  echo "❌ prod に必須 env が不足: ${MISSING_ENVS[*]}"
  echo "   先に手動で追加してください:"
  echo "     az containerapp secret set --name $APP_NAME --resource-group $RG_NAME --secrets ..."
  echo "     az containerapp update     --name $APP_NAME --resource-group $RG_NAME --set-env-vars ..."
  if [[ "$DRY_RUN" != "1" ]]; then
    read -r -p "それでも続行しますか? (yes/NO): " ans
    [[ "$ans" == "yes" ]] || exit 1
  fi
fi

# TRANSCRIPT_SOURCE が graph のままだと WS デプロイしても bot 投入されない
TS_VALUE="$(echo "$EXISTING_ENV_JSON" | python3 -c \
  "import json,sys;
data=json.load(sys.stdin);
print(next((e.get('value','') for e in data if e.get('name')=='TRANSCRIPT_SOURCE'), ''))" 2>/dev/null || echo "")"
if [[ -n "$TS_VALUE" && "$TS_VALUE" == "graph" ]]; then
  echo ""
  echo "⚠️  TRANSCRIPT_SOURCE=graph のままです。WS 経路で bot が投入されません。"
  echo "    今回の更新と一緒に変更する場合は scripts/deploy_recall_ws.sh の env block に"
  echo "    TRANSCRIPT_SOURCE=both を追加するか、別途以下を実行:"
  echo "    az containerapp update -n $APP_NAME -g $RG_NAME --set-env-vars TRANSCRIPT_SOURCE=both"
  if [[ "$DRY_RUN" != "1" ]]; then
    read -r -p "続行しますか? (yes/NO): " ans
    [[ "$ans" == "yes" ]] || exit 1
  fi
fi

# RECALL_WEBHOOK_PUBLIC_URL が legacy /api/recall/transcript を指していたら警告
WH_URL_VALUE="$(echo "$EXISTING_ENV_JSON" | python3 -c \
  "import json,sys;
data=json.load(sys.stdin);
print(next((e.get('value','') for e in data if e.get('name')=='RECALL_WEBHOOK_PUBLIC_URL'), ''))" 2>/dev/null || echo "")"
if [[ "$WH_URL_VALUE" == *"/api/recall/transcript" ]]; then
  echo ""
  echo "🔴 SECURITY WARNING:"
  echo "   prod の RECALL_WEBHOOK_PUBLIC_URL が legacy /api/recall/transcript (無認証) を指しています。"
  echo "   現状 prod は無認証 webhook を受けている可能性があります。"
  echo "   一緒に /api/recall/webhook (HMAC 検証あり) に切り替えることを推奨。"
  echo "   このスクリプトは触らないので別途実行:"
  echo "     az containerapp update -n $APP_NAME -g $RG_NAME --set-env-vars \\"
  echo "       RECALL_WEBHOOK_PUBLIC_URL=https://<fqdn>/api/recall/webhook"
  if [[ "$DRY_RUN" != "1" ]]; then
    read -r -p "続行しますか? (yes/NO): " ans
    [[ "$ans" == "yes" ]] || exit 1
  fi
fi

# ── 1. terraform apply ──────────────────────────────────────
if [[ "$SKIP_TF" != "1" ]]; then
  echo "::: 1. terraform apply (ingress.transport=http と recall_ws_url 反映)"
  pushd infra >/dev/null
  run terraform init -upgrade
  run terraform plan -out=ws.tfplan
  echo ">>> 上記 plan を確認してください。続行する場合は Enter、中止は Ctrl-C"
  if [[ "$DRY_RUN" != "1" ]]; then read -r _; fi
  run terraform apply ws.tfplan
  WS_URL="$(terraform output -raw recall_ws_url 2>/dev/null || true)"
  popd >/dev/null
  echo "WS URL = $WS_URL"
fi

# WS URL は output から取れなければ env で渡してもらう
WS_URL="${WS_URL:-${RECALL_WS_PUBLIC_URL:-}}"
if [[ -z "$WS_URL" ]]; then
  WS_URL="wss://$(az containerapp show --name "$APP_NAME" --resource-group "$RG_NAME" --query properties.latestRevisionFqdn -o tsv)/api/recall/ws"
fi
echo "RECALL_WS_PUBLIC_URL=$WS_URL"

# ── 2. Docker build & push ──────────────────────────────────
ACR_LOGIN_SERVER="${ACR_NAME}.azurecr.io"
FULL_IMAGE="${ACR_LOGIN_SERVER}/${IMAGE_NAME}:${IMAGE_TAG}"

if [[ "$SKIP_BUILD" != "1" ]]; then
  echo "::: 2. Docker build & push: $FULL_IMAGE"
  run az acr login --name "$ACR_NAME"
  # Container Apps は linux/amd64 で動く。Apple Silicon からのビルドは buildx で明示する。
  run docker buildx build \
    --platform linux/amd64 \
    -t "$FULL_IMAGE" \
    --push \
    .
fi

# ── 3. Container App に WS 関連 env を追加 ──────────────────
if [[ "$SKIP_DEPLOY" != "1" ]]; then
  echo "::: 3. Container App env を更新"
  # WS_PUBLIC_URL は secret として登録（URL 自体は機密ではないが既存パターンに合わせる）
  run az containerapp secret set \
    --name "$APP_NAME" \
    --resource-group "$RG_NAME" \
    --secrets "recall-ws-public-url=$WS_URL"

  # --set-env-vars は既存 env を温存しつつ追加 / 上書きする
  run az containerapp update \
    --name "$APP_NAME" \
    --resource-group "$RG_NAME" \
    --set-env-vars \
      "RECALL_TRANSPORT=$RECALL_TRANSPORT" \
      "RECALL_WS_PUBLIC_URL=secretref:recall-ws-public-url" \
      "RECALL_AUDIO_SINK=$RECALL_AUDIO_SINK"

  # ── 4. イメージを新リビジョンに反映 ─────────────────────
  echo "::: 4. Container App image を新タグへ更新"
  run az containerapp update \
    --name "$APP_NAME" \
    --resource-group "$RG_NAME" \
    --image "$FULL_IMAGE"
fi

# ── 5. Smoke test ────────────────────────────────────────────
echo "::: 5. smoke test (WS 配線確認)"
FQDN="$(az containerapp show --name "$APP_NAME" --resource-group "$RG_NAME" --query properties.latestRevisionFqdn -o tsv)"
HTTPS_URL="https://${FQDN}/api/recall/ws"

# 認証ヘッダ無しで Upgrade を試みると 401 が返ること（= ルートが配線されている証拠）
# curl は WS upgrade を完了しないので、status だけ取り出す
echo "smoke-test: GET (no auth) $HTTPS_URL  期待 status=401"
if [[ "$DRY_RUN" != "1" ]]; then
  status="$(curl -s -o /dev/null -w '%{http_code}' \
    -H 'Connection: Upgrade' \
    -H 'Upgrade: websocket' \
    -H 'Sec-WebSocket-Version: 13' \
    -H 'Sec-WebSocket-Key: dGVzdHRlc3R0ZXN0dGVzdA==' \
    "$HTTPS_URL")"
  echo "actual status=$status"
  if [[ "$status" != "401" ]]; then
    echo "⚠️  期待値 401 と異なります。ログを確認してください："
    echo "    az containerapp logs show -n $APP_NAME -g $RG_NAME --tail 100"
    exit 1
  fi
fi

echo ""
echo "✅ デプロイ完了。次にやること:"
echo "  1) Recall.ai dashboard で Workspace secret を発行（または既存値を確認）"
echo "  2) bot 作成時に realtime_endpoints に WS URL が渡るのは"
echo "     src/transcript/recall_client.py が自動で行う"
echo "  3) ログ監視:"
echo "       az containerapp logs show -n $APP_NAME -g $RG_NAME --follow"
