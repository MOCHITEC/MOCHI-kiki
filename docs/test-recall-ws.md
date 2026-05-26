# Recall.ai WebSocket テスト運用マニュアル

本番 Container App に対し、Recall.ai bot を手動で投入して WebSocket 経路の動作を確認する手順。

---

## 前提

- `.env` に以下が入っていること:
  - `RECALL_API_KEY`
  - `RECALL_WEBHOOK_SECRET`
  - `RECALL_REGION` (例: `ap-northeast-1`)
  - `AZURE_COSMOS_ENDPOINT` / `AZURE_COSMOS_KEY`
- `az login` 済
- `jq` / `python3` インストール済

---

## 0. ターミナル準備（2 つ開く）

| ターミナル | 用途 |
|---|---|
| ターミナル A | **ログ tail 用**（常時開きっぱなし） |
| ターミナル B | **bot 投入・確認用** |

---

## 1. ログを tail（ターミナル A）

### 1-1. 全部流す
```bash
az containerapp logs show -n mochikiki-bot-dev -g rg-mochi-kiki --follow
```

### 1-2. WS 関連だけ見たい
Cosmos のデバッグログがうるさいので、`recall_ws_handler` だけ grep：

```bash
az containerapp logs show -n mochikiki-bot-dev -g rg-mochi-kiki --follow \
  | grep --line-buffered recall_ws_handler
```

### 1-3. 直近のログだけ確認（follow しない）
```bash
az containerapp logs show -n mochikiki-bot-dev -g rg-mochi-kiki --tail 50
```

### 1-4. KQL で過去を遡る（Log Analytics、Azure Portal）
Log Analytics Workspace `mochikiki-law-dev` に対して：

```kusto
ContainerAppConsoleLogs_CL
| where ContainerAppName_s == "mochikiki-bot-dev"
| where Log_s contains "recall_ws_handler"
| order by TimeGenerated desc
| take 100
```

---

## 2. bot 投入（ターミナル B）

### 2-1. 推奨：スクリプトで一発
```bash
cd /Users/uedaryou/mochitec/repositories/MOCHI-kiki
./scripts/test_recall_ws.sh "https://teams.live.com/meet/9372994450983?p=u0dNzoMtuKXJ7zND2p"
```

スクリプトが：
1. Recall.ai bot を投入 → `bot_id` を取得
2. Cosmos `meetings` に test レコードを upsert (`recall_bot_id=<bot_id>`)
3. 終了用 curl コマンドを表示

> ⚠️ Teams の会議 URL は **必ずダブルクォートで囲む**。クエリパラメータ `?p=...` が解釈されない / 改行で切れないように。

### 2-2. 手動で curl を叩く（スクリプトを使わない場合）

```bash
# 環境変数を準備
RECALL_KEY=$(grep '^RECALL_API_KEY=' .env | cut -d= -f2-)
RECALL_REGION=$(grep '^RECALL_REGION=' .env | cut -d= -f2-)
FQDN=$(az containerapp show -n mochikiki-bot-dev -g rg-mochi-kiki \
        --query properties.configuration.ingress.fqdn -o tsv)
WS_URL="wss://${FQDN}/api/recall/ws"
MEETING_URL="https://teams.live.com/meet/..."

# bot 投入
RESP=$(curl -sS -X POST "https://${RECALL_REGION}.recall.ai/api/v1/bot" \
  -H "Authorization: Token $RECALL_KEY" \
  -H "Content-Type: application/json" \
  -d "{
    \"meeting_url\": \"$MEETING_URL\",
    \"bot_name\": \"MOCHI-kiki-test\",
    \"recording_config\": {
      \"transcript\": {\"provider\": {\"recallai_streaming\": {\"language_code\": \"ja\"}}},
      \"audio_mixed_raw\": {},
      \"realtime_endpoints\": [
        {
          \"type\": \"websocket\",
          \"url\": \"$WS_URL\",
          \"events\": [\"audio_mixed_raw.data\", \"transcript.data\"]
        }
      ]
    }
  }")

BOT_ID=$(echo "$RESP" | jq -r .id)
echo "Bot ID: $BOT_ID"

# Cosmos に meetings レコード手動 upsert（test_recall_ws.sh と同じ Python 部分を流用 or
# az cosmosdb sql query で直接 INSERT。スクリプト使うのが楽）
```

---

## 3. 期待するログの流れ（ターミナル A）

### 3-1. 成功パターン
```
[GET /api/recall/ws HTTP/1.1" 101 0]            ← Upgrade 成功
WS established remote=100.100.0.113              ← 接続確立
（しばらく無音 / または Cosmos のデバッグログ）
（音声・transcript の処理ログ）
...
closed bot_id=<bot_id> msgs=N audio_bytes=N drops=0   ← 切断時のサマリ
```

### 3-2. よく見るエラーパターン

| ログ | 意味 | 対処 |
|---|---|---|
| `401` (curl) | 認証ヘッダ無しで叩いた | 正常（smoke test） |
| `401` (Recall) | HMAC secret 不一致 | `RECALL_WEBHOOK_SECRET` が dashboard と prod で一致しているか確認 |
| `meeting_id 解決失敗 bot_id=... → 1008 close` | Cosmos `meetings` に `recall_bot_id=<bot_id>` が無い | スクリプトの Cosmos upsert が遅れて Recall 接続より後になった可能性。3 秒ごとに自動リトライされるので待つ |
| `JSON parse failed` | Recall envelope の形式異常 | 公式 spec 確認 |
| `base64 decode failed` | 音声フレームの破損 | 通常レアケース。低品質回線で発生し得る |
| `重複 svix-id を無視` | 同じメッセージ重複受信 | リプレイ防御。無害 |

### 3-3. 順序問題（重要）

Recall.ai は bot 作成直後 **1〜2 秒以内** に WS 接続を試みます。
test スクリプトの Cosmos upsert は **3〜5 秒**かかるので、最初の数回の接続は `meeting_id 解決失敗` で 1008 close になります。

Recall は **3 秒間隔で最大 30 回**自動リトライするので、Cosmos upsert 完了後の次のリトライで成功します（最大 90 秒以内）。

ログ上のタイムライン例：
```
T+0   bot 作成 → bot_id 取得
T+1   WS 接続 #1 → 1008 close (Cosmos miss)
T+4   WS 接続 #2 → 1008 close (Cosmos miss)
T+5   Cosmos upsert 完了
T+7   WS 接続 #3 → established (Cosmos hit) ✅
```

---

## 4. bot の状態確認

```bash
RECALL_KEY=$(grep '^RECALL_API_KEY=' .env | cut -d= -f2-)
RECALL_REGION=$(grep '^RECALL_REGION=' .env | cut -d= -f2-)
BOT_ID="<bot_id を貼る>"

# bot のメタ情報
curl -s -H "Authorization: Token $RECALL_KEY" \
  "https://${RECALL_REGION}.recall.ai/api/v1/bot/${BOT_ID}/" | jq .

# 状態遷移だけ
curl -s -H "Authorization: Token $RECALL_KEY" \
  "https://${RECALL_REGION}.recall.ai/api/v1/bot/${BOT_ID}/" \
  | jq '{id, status_changes, meeting_metadata}'
```

`status_changes` の最新が `in_call_recording` ならアクティブ、`call_ended` / `done` / `fatal` なら終了。

---

## 5. テスト終了

### 5-1. bot を会議から退出させる
```bash
RECALL_KEY=$(grep '^RECALL_API_KEY=' .env | cut -d= -f2-)
RECALL_REGION=$(grep '^RECALL_REGION=' .env | cut -d= -f2-)
BOT_ID="<bot_id>"

curl -X POST "https://${RECALL_REGION}.recall.ai/api/v1/bot/${BOT_ID}/leave_call/" \
  -H "Authorization: Token $RECALL_KEY"
```

⚠️ **bot を残したまま放置すると Recall の料金が発生し続ける**ので、テスト後は必ず退出させること。

### 5-2. Cosmos に作った test meetings レコードを削除（任意）
```bash
TEST_MEETING_ID="test-1779679072"   # スクリプト出力の id を貼る

az cosmosdb sql container show -a mochikiki-cosmos-dev -g rg-mochi-kiki \
  -d meeting_db -n meetings >/dev/null

# 削除は Cosmos Data Explorer (Azure Portal) で id 検索 → Delete が楽
# CLI でやるなら:
python3 - <<PYEOF
import asyncio, os
from azure.cosmos.aio import CosmosClient
async def main():
    client = CosmosClient(os.environ["AZURE_COSMOS_ENDPOINT"], credential=os.environ["AZURE_COSMOS_KEY"])
    db = client.get_database_client(os.environ.get("COSMOS_DATABASE", "meeting_db"))
    c = db.get_container_client("meetings")
    await c.delete_item("$TEST_MEETING_ID", partition_key="$TEST_MEETING_ID")
    await client.close()
    print("deleted")
asyncio.run(main())
PYEOF
```

---

## 6. トラブルシュート

### bot 投入が `authentication_failed`
- `.env` の `RECALL_REGION` と `RECALL_API_KEY` が同じ region のものか確認
- Recall dashboard で key が revoked になっていないか確認
- 各 region で probe：
  ```bash
  RECALL_KEY=$(grep '^RECALL_API_KEY=' .env | cut -d= -f2-)
  for r in us-east-1 us-west-2 eu-central-1 ap-northeast-1; do
    s=$(curl -s -o /dev/null -w "%{http_code}" -H "Authorization: Token $RECALL_KEY" "https://${r}.recall.ai/api/v1/bot/")
    echo "  $r: HTTP $s"
  done
  ```
  200/204/401 が返る region が正解（401 は「形式は正しいが何か別の認可問題」/200 は通った/403 は別 region）

### bot 投入が `Validation Error: meeting_url`
- Teams URL が壊れていないか確認（コピペで改行が入ると壊れる）
- `https://teams.microsoft.com/` か `https://teams.live.com/` で始まること

### WS が `101` で確立しないまま 401 を返す
- HMAC secret 不一致。Container App の `RECALL_WEBHOOK_SECRET` と Recall dashboard の secret を再確認
- 時刻ズレ (5 分以上) → Container App のサーバ時刻を確認

### `1008 close` が連続して止まらない
- Cosmos `meetings` に対応レコードが無い
- レコード upsert 後に **新しい bot を再投入** が確実
- 30 回のリトライウィンドウ (90 秒) を過ぎると Recall 側で `failed` 扱いとなり以降 retry されない

### Cosmos デバッグログがうるさい
原因：`azure-cosmos` の python ロガーがデフォルトで詳細出力。
将来対策：`src/main.py` の logging 設定で `logging.getLogger("azure").setLevel(logging.WARNING)` を追加。
当面は ターミナル A で `grep` で recall_ws_handler だけ抽出すれば OK。

---

## 7. 関連ファイル早見表

| ファイル | 用途 |
|---|---|
| `scripts/test_recall_ws.sh` | bot 投入 + Cosmos upsert の自動化 |
| `scripts/bootstrap_prod_env.sh` | 初回 Container App env セットアップ |
| `scripts/deploy_recall_ws.sh` | image ビルド & デプロイ |
| `scripts/fetch_azure_env.sh` | Azure リソースから .env を自動生成 |
| `src/transcript/recall_ws_handler.py` | WS 受信ハンドラ本体 |
| `src/transcript/recall_client.py` | Recall API クライアント (bot 作成) |
| `docs/api-server.md` | API エンドポイント仕様 |
| `docs/deploy-recall-ws.md` | デプロイ全般の手順 |
