# Recall.ai WebSocket デプロイ手順

既に稼働中の MOCHI-kiki Container App に対し、Recall.ai WebSocket 経路 (`/api/recall/ws`) を有効化する更新手順。

---

## 0. 事前準備（一度だけ）

| 項目 | 取得方法 |
|---|---|
| `az login` 済 | `az account show` で確認 |
| docker buildx | `docker buildx version` で確認（Apple Silicon → linux/amd64 ビルド用） |
| Recall.ai workspace secret | Recall.ai ダッシュボード → API Keys |
| 既存 Recall.ai 関連の env が prod に入っているか | `az containerapp show -n mochikiki-bot-dev -g rg-mochi-kiki --query "properties.template.containers[0].env"` |

### 必要な既存 env（無ければ追加）
- `RECALL_API_KEY` （ダッシュボードの API key）
- `RECALL_WEBHOOK_SECRET` （Workspace signing secret）
- `RECALL_REGION` （例: `us-east-1`）
- `RECALL_BOT_NAME` （任意。デフォルト `MOCHI-kiki`）
- `RECALL_TRANSCRIPT_LANGUAGE` （任意。デフォルト `ja`）
- `RECALL_WEBHOOK_PUBLIC_URL` （webhook も併用するなら）
- `TRANSCRIPT_SOURCE` （`recall` か `both` でないと bot が投入されない）

---

## 1. 自動デプロイ（推奨）

```bash
# プロジェクトルートで
./scripts/deploy_recall_ws.sh
```

このスクリプトが実行する処理:
1. `terraform apply` — `ingress.transport=http` 追加と `recall_ws_url` output 追加
2. `docker buildx build --platform linux/amd64 --push` で ACR に push
3. `az containerapp secret set` で `recall-ws-public-url` を登録
4. `az containerapp update --set-env-vars` で 7 個の WS 関連 env を追加
5. `az containerapp update --image` で新リビジョンに切り替え
6. `curl` で `/api/recall/ws` に Upgrade を投げて 401 が返ることを確認

### 主要な切替フラグ（env で渡す）

```bash
# webhook と WS を並走（Phase 5 推奨）
RECALL_TRANSPORT=both ./scripts/deploy_recall_ws.sh

# WS 単独運用（Phase 6）
RECALL_TRANSPORT=websocket ./scripts/deploy_recall_ws.sh

# 音声を Cosmos に保存せずファイルに dump して確認したい
RECALL_AUDIO_SINK=file ./scripts/deploy_recall_ws.sh

# ビルドだけスキップして env 切替のみ
SKIP_BUILD=1 SKIP_TF=1 ./scripts/deploy_recall_ws.sh

# 全部 echo して中身を見る
DRY_RUN=1 ./scripts/deploy_recall_ws.sh
```

---

## 2. 手動デプロイ（スクリプトを使わない場合）

### 2-1. Terraform 適用

```bash
cd infra
terraform plan -out=ws.tfplan
terraform apply ws.tfplan
WS_URL=$(terraform output -raw recall_ws_url)
echo "$WS_URL"   # wss://mochikiki-bot-dev--xxxxx.../api/recall/ws
```

### 2-2. イメージビルド & push

```bash
cd ..  # プロジェクトルート
az acr login --name mochikikiacrdev

TAG="ws-$(date +%Y%m%d-%H%M%S)"
IMAGE="mochikikiacrdev.azurecr.io/mochi-kiki-bot:$TAG"

docker buildx build --platform linux/amd64 -t "$IMAGE" --push .
```

### 2-3. Container App の env を追加

```bash
APP=mochikiki-bot-dev
RG=rg-mochi-kiki

az containerapp secret set \
  --name "$APP" --resource-group "$RG" \
  --secrets "recall-ws-public-url=$WS_URL"

az containerapp update \
  --name "$APP" --resource-group "$RG" \
  --set-env-vars \
    "RECALL_TRANSPORT=both" \
    "RECALL_WS_PUBLIC_URL=secretref:recall-ws-public-url" \
    "RECALL_WS_EVENTS=audio_mixed_raw.data,transcript.data" \
    "RECALL_WS_MAX_FRAME_BYTES=1048576" \
    "RECALL_WS_QUEUE_MAX_BYTES=1048576" \
    "RECALL_AUDIO_SINK=noop" \
    "RECALL_WEBHOOK_DRY_RUN=false"
```

### 2-4. イメージを新リビジョンに反映

```bash
az containerapp update \
  --name "$APP" --resource-group "$RG" \
  --image "$IMAGE"
```

### 2-5. Smoke test

```bash
FQDN=$(az containerapp show -n "$APP" -g "$RG" --query properties.latestRevisionFqdn -o tsv)

curl -i \
  -H "Connection: Upgrade" \
  -H "Upgrade: websocket" \
  -H "Sec-WebSocket-Version: 13" \
  -H "Sec-WebSocket-Key: dGVzdHRlc3R0ZXN0dGVzdA==" \
  "https://${FQDN}/api/recall/ws"
# 期待: HTTP/1.1 401 Unauthorized
# （ルートが配線されている証拠。auth 不備のため 401 になる）
```

---

## 3. Recall.ai 側

### 3-1. ダッシュボード側で追加の登録は不要
WS endpoint は **bot 作成時** に `recording_config.realtime_endpoints[]` で渡す形式。`RecallBotClient._build_create_body` が自動で組み立てるので、Recall.ai ダッシュボードで Webhook URL を変更する必要はありません。

### 3-2. Workspace secret の確認
Recall.ai ダッシュボード → **API Keys** → **Verification secret** が prod の `RECALL_WEBHOOK_SECRET` と一致していること。

### 3-3. 既存 webhook 登録の扱い
- `RECALL_TRANSPORT=both` 期間中は、既存の Recall webhook 登録もそのまま残してよい（二重受信になるが、`RECALL_WEBHOOK_DRY_RUN=false` のままだと utterance が二重保存されるので注意）
- 二重保存を避けたい場合は `RECALL_WEBHOOK_DRY_RUN=true` を **追加で** set
- `RECALL_TRANSPORT=websocket` に切替後は、Recall.ai ダッシュボードの webhook 登録は外す or 残しても無害（送信先がもう Webhook を返さなくなるだけ）

---

## 4. デプロイ後の監視

### ログを流す
```bash
az containerapp logs show \
  --name mochikiki-bot-dev \
  --resource-group rg-mochi-kiki \
  --follow
```

### 期待する正常時ログ
```
INFO:src.transcript.recall_ws_handler:RecallWsHandler: WS established remote=<recall-ip>
INFO:src.transcript.recall_ws_handler:RecallWsHandler: closed bot_id=bot_xxx msgs=<n> audio_bytes=<n>
```

### Log Analytics クエリ
```kql
ContainerAppConsoleLogs_CL
| where ContainerAppName_s == "mochikiki-bot-dev"
| where Log_s contains "recall_ws_handler"
| order by TimeGenerated desc
| take 100
```

---

## 5. ロールバック

### 即時（env だけ戻す）
```bash
az containerapp update \
  --name mochikiki-bot-dev --resource-group rg-mochi-kiki \
  --set-env-vars RECALL_TRANSPORT=webhook
```

### イメージも戻す（前タグへ）
```bash
az containerapp revision list \
  -n mochikiki-bot-dev -g rg-mochi-kiki \
  --query "[].{name:name, image:properties.template.containers[0].image, active:properties.active}" \
  -o table

az containerapp update \
  -n mochikiki-bot-dev -g rg-mochi-kiki \
  --image <前タグの完全パス>
```

---

## 6. トラブルシュート早見表

| 症状 | 原因の見立て | 対処 |
|---|---|---|
| smoke test で 404 | image が新しくない / `app.py` の WS ルート未登録 | `az containerapp revision show` で active revision の image を確認 |
| smoke test で 502 | コンテナ起動失敗 | ログを `--tail 200` で確認、Config の env 不足が典型 |
| WS established 後すぐ 1008 close | `data.bot.id` から `meeting_id` 解決失敗 | Cosmos `meetings` に対象 `recall_bot_id` doc があるか確認 |
| WS が確立すらされない | Recall が 30 回 3 秒で再試行して `failed` | ingress.transport が `http` か / 証明書有効か / `RECALL_WS_PUBLIC_URL` 値が正しいか |
| 認証で 401 が続く | secret / clock skew | `RECALL_WEBHOOK_SECRET` が両側で一致、Container Apps 側時刻 OK |
| `audio_mixed_raw.data` が来ない | `recording_config.audio_mixed_raw` 抜け | `RECALL_WS_EVENTS` に `audio_mixed_raw.data` を含めて再デプロイ（`RecallBotClient` 側で自動付与される）|
