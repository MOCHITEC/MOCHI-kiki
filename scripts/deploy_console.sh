#!/usr/bin/env bash
#
# 管理コンソール (frontend-bot-console) を既存 Container App に追加 deploy する。
# 仕様: docs/superpowers/specs/2026-05-29-frontend-bot-console.md (Phase B + E)
#
# 何をするか:
#   0. 前提コマンド / az login / resource 存在チェック
#   1. CONSOLE_USERNAME / PASSWORD / JWT secret を決定
#   2. Container App の secret に CONSOLE_* を登録
#   3. Container App の env を追加 (既存 env はマージで保持)
#   4. Dockerfile から新 image を build → ACR push
#   5. Container App の image を切り替えて新 revision を作る
#   6. /api/console/auth/me に curl して 401 が返ることをスモークテスト
#   7. frontend/.env.local に書くべき BACKEND_URL を表示
#
# 安全策:
#   --dry-run             : 実際の az 呼び出しを echo するだけ
#   --skip-build          : Docker build / push を skip (env 追加だけしたいとき)
#   --user / --password   : 既定 admin/admin を上書き
#
# 前提:
#   - az login 済み
#   - リポジトリ root で実行 (Dockerfile / pyproject.toml が必要)
#   - python3 + bcrypt がローカルにある (パスワードハッシュ用)
#   - docker daemon が動いている (--skip-build 指定時は不要)

set -euo pipefail

# ===== 引数 =====
DRY_RUN=0
SKIP_BUILD=0
USERNAME="admin"
PASSWORD="admin"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=1; shift ;;
    --skip-build) SKIP_BUILD=1; shift ;;
    --user) USERNAME="$2"; shift 2 ;;
    --password) PASSWORD="$2"; shift 2 ;;
    -h|--help)
      sed -n '2,30p' "$0"
      exit 0
      ;;
    *) echo "unknown arg: $1" >&2; exit 1 ;;
  esac
done

# ===== Terraform 変数 (infra/variables.tf の default に揃える) =====
PREFIX="${TF_PREFIX:-mochikiki}"
ENVIRONMENT="${TF_ENV:-dev}"
RESOURCE_GROUP="${TF_RG:-rg-mochi-kiki}"

CONTAINER_APP_NAME="${PREFIX}-bot-${ENVIRONMENT}"
ACR_NAME="${PREFIX}acr${ENVIRONMENT}"
IMAGE_REPO="mochi-kiki/bot"
IMAGE_TAG="console-$(date +%Y%m%d%H%M%S)"

# ===== ヘルパ =====
run() {
  if (( DRY_RUN )); then
    echo "[dry-run] $*"
  else
    eval "$@"
  fi
}

require() {
  command -v "$1" >/dev/null 2>&1 || { echo "ERROR: '$1' が見つかりません" >&2; exit 1; }
}

# ===== 0. 前提チェック =====
echo "=== 0. 前提チェック ==="
require az
require python3
require openssl
require curl
(( SKIP_BUILD )) || require docker

az account show >/dev/null 2>&1 || { echo "ERROR: az login してください" >&2; exit 1; }

python3 -c "import bcrypt" 2>/dev/null || {
  echo "ERROR: python3 に bcrypt がありません。"
  echo "       pip install bcrypt"
  exit 1
}

# Container App 存在
az containerapp show \
  --name "$CONTAINER_APP_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --query name -o tsv >/dev/null 2>&1 || {
  echo "ERROR: Container App '$CONTAINER_APP_NAME' が RG '$RESOURCE_GROUP' に見つかりません"
  echo "       TF_PREFIX / TF_ENV / TF_RG を環境に合わせて再実行してください"
  exit 1
}

# ACR 存在
az acr show --name "$ACR_NAME" --query name -o tsv >/dev/null 2>&1 || {
  echo "ERROR: ACR '$ACR_NAME' が見つかりません"
  exit 1
}
echo "  ✓ az login OK / Container App / ACR 存在"

# ===== 1. パスワードハッシュ / JWT secret 生成 =====
echo ""
echo "=== 1. credentials 生成 ==="
PW_HASH=$(python3 -c "import bcrypt,sys; print(bcrypt.hashpw(sys.argv[1].encode(),bcrypt.gensalt(12)).decode())" "$PASSWORD")
JWT_SECRET=$(openssl rand -hex 64)
echo "  CONSOLE_USERNAME=${USERNAME}"
echo "  CONSOLE_PASSWORD_HASH=${PW_HASH:0:24}... (bcrypt cost=12)"
echo "  CONSOLE_JWT_SECRET=${JWT_SECRET:0:12}... (64-byte hex)"

# ===== 2. Container App secret 登録 =====
echo ""
echo "=== 2. Container App secret 登録 ==="
echo "  既存 secret 一覧:"
az containerapp secret list \
  --name "$CONTAINER_APP_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --query "[].name" -o tsv | sed 's/^/    /'

run "az containerapp secret set \
  --name \"$CONTAINER_APP_NAME\" \
  --resource-group \"$RESOURCE_GROUP\" \
  --secrets \
    'console-password-hash=${PW_HASH}' \
    'console-jwt-secret=${JWT_SECRET}' \
  >/dev/null"
echo "  ✓ console-password-hash / console-jwt-secret を upsert"

# ===== 3. Container App env 追加 =====
echo ""
echo "=== 3. Container App env 追加 (--set-env-vars はマージ) ==="
run "az containerapp update \
  --name \"$CONTAINER_APP_NAME\" \
  --resource-group \"$RESOURCE_GROUP\" \
  --set-env-vars \
    'CONSOLE_ENABLED=true' \
    'CONSOLE_USERNAME=${USERNAME}' \
    'CONSOLE_PASSWORD_HASH=secretref:console-password-hash' \
    'CONSOLE_JWT_SECRET=secretref:console-jwt-secret' \
    'CONSOLE_COOKIE_SECURE=true' \
  >/dev/null"
echo "  ✓ env 追加"

# ===== 4. Docker build + ACR push =====
ACR_LOGIN_SERVER=$(az acr show --name "$ACR_NAME" --query loginServer -o tsv)
FULL_IMAGE="${ACR_LOGIN_SERVER}/${IMAGE_REPO}:${IMAGE_TAG}"

if (( SKIP_BUILD )); then
  echo ""
  echo "=== 4. Docker build / push (--skip-build なのでスキップ) ==="
  echo "  既存 image をそのまま使う (新コードは反映されません!)"
else
  echo ""
  echo "=== 4. Docker build + ACR push ==="
  run "az acr login --name \"$ACR_NAME\""
  # Container App は linux/amd64 を要求。Apple Silicon でも明示してビルド。
  run "docker buildx build --platform linux/amd64 --provenance=false -t \"$FULL_IMAGE\" --push ."
  # buildx --push でアップロード済みなので docker push は不要
  echo "  ✓ push: ${FULL_IMAGE}"
fi

# ===== 5. Container App revision rollout =====
echo ""
echo "=== 5. Container App revision rollout ==="
if (( SKIP_BUILD )); then
  # image 切替なしでも env 反映のため revision restart
  run "az containerapp revision restart \
    --name \"$CONTAINER_APP_NAME\" \
    --resource-group \"$RESOURCE_GROUP\" \
    --revision \$(az containerapp revision list -n \"$CONTAINER_APP_NAME\" -g \"$RESOURCE_GROUP\" --query '[?properties.active].name' -o tsv) \
    >/dev/null || true"
else
  run "az containerapp update \
    --name \"$CONTAINER_APP_NAME\" \
    --resource-group \"$RESOURCE_GROUP\" \
    --image \"$FULL_IMAGE\" \
    >/dev/null"
fi
echo "  ✓ rollout 指示"

# ===== 6. URL & スモークテスト =====
FQDN=$(az containerapp show \
  --name "$CONTAINER_APP_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --query "properties.configuration.ingress.fqdn" -o tsv)

URL="https://${FQDN}"

echo ""
echo "=== 6. スモークテスト ==="
echo "  Container App URL: ${URL}"

if (( ! DRY_RUN )); then
  echo "  /api/console/auth/me に curl..."
  smoke_ok=0
  for i in 1 2 3 4 5 6 7 8; do
    code="$(curl -s -o /dev/null -w "%{http_code}" "${URL}/api/console/auth/me" 2>/dev/null || echo "000")"
    if [[ "$code" == "401" ]]; then
      echo "  ✓ 401 unauthorized (=ルート有効)"
      smoke_ok=1
      break
    fi
    echo "  ...$i 回目 HTTP $code、15 秒待って再試行"
    sleep 15
  done
  (( smoke_ok )) || echo "  ⚠ スモークテスト未通過。Container App ログを確認してください"
fi

# ===== 7. frontend 設定指示 =====
echo ""
echo "==========================================================="
echo "  Deploy 完了 (admin / ${PASSWORD})"
echo ""
echo "  → frontend/.env.local に追記:"
echo "      BACKEND_URL=${URL}"
echo ""
echo "  → frontend dev server 再起動:"
echo "      cd frontend && npm run dev"
echo "==========================================================="
