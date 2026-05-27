# Recall.ai bot 投入クイックスタート

Teams 会議に Recall.ai bot を投入し、文字起こしを Cosmos に取り込むまでの最短手順。
詳細な運用 / トラブルシュートは [test-recall-ws.md](./test-recall-ws.md) を参照。

---

## 前提 (一度きりの準備)

1. `.env` に以下が入っていること (`./scripts/fetch_azure_env.sh` で取得済の想定)
   - `RECALL_API_KEY`
   - `RECALL_REGION` (例: `us-west-2` または `ap-northeast-1`)
   - `AZURE_COSMOS_ENDPOINT` / `AZURE_COSMOS_KEY`
2. `az login` 済
3. `jq` / `python3` インストール済 (`brew install jq` 等)

---

## 手順 (3 ステップ)

### 1. bot を投入

```bash
./scripts/test_recall_ws.sh "<TEAMS_MEETING_URL>"
```

例:
```bash
./scripts/test_recall_ws.sh "https://teams.live.com/meet/9376323436183?p=Ir4cn611R861uOg6v4"
```

確認画面で **Enter** を押すと bot が会議に入る。出力末尾に `BOT_ID=...` が表示されるので控えておく。

### 2. 会議で発話 → bot を退出させる

Teams 側で bot の参加を **許可**し、会議で話す。終わったら以下で bot を退出:

```bash
source .env && curl -X POST \
  -H "Authorization: Token $RECALL_API_KEY" \
  "https://$RECALL_REGION.recall.ai/api/v1/bot/<BOT_ID>/leave_call/"
```

### 3. 文字起こしを確認

```bash
# 直近の meeting 一覧
python3 scripts/show_transcript.py

# 該当 meeting の詳細
python3 scripts/show_transcript.py <BOT_ID>

# テキストだけ取り出して保存
python3 scripts/show_transcript.py <BOT_ID> --plain > transcript.txt
```

> 注: 現状の運用ではテストスクリプト投入の場合 `meeting_id == bot_id` になる
> (MeetingBot 経由ではない fallback 挙動)。`scripts/show_transcript.py` の引数には
> bot_id をそのまま渡せばよい。

---

## トラブル時のチェックポイント

| 症状 | 確認 |
|---|---|
| bot 投入で `❌ bot 投入失敗` | 表示された JSON を見る。`language_code other than english is not supported in low latency mode` などはコード側で吸収済のはず |
| bot が waiting room から進まない | Teams 側で参加許可していない |
| `show_transcript.py` が空 | bot が join 前に切れた / `is_final` 抜き payload の reject 退行 → Log Analytics の `transcript_final=` を確認 |
| Cosmos 接続エラー | `.env` の `AZURE_COSMOS_*` を確認 |

詳細ログ確認コマンドは [test-recall-ws.md](./test-recall-ws.md#1-ログを-tailターミナル-a) を参照。
