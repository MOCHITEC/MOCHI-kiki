# MOCHI-kiki API サーバー利用マニュアル

## 概要

MOCHI-kiki の API サーバーは既存の Bot Framework サーバー（port 3978）に統合されています。Teams Bot としての動作に加え、外部サービスからの Webhook を受け付けるエンドポイントを提供します。

現在提供しているエンドポイント:

| エンドポイント | 用途 |
|---|---|
| `POST /api/recall/transcript` | Recall.ai からの音声文字起こし結果を受信する |
| `POST /api/messages` | Bot Framework の Teams メッセージを受信する（Bot Framework 内部） |

---

## エンドポイント詳細

### `POST /api/recall/transcript`

Recall.ai ボットが Teams 会議内で文字起こしたテキストをリアルタイムに受信し、Orchestrator パイプラインに流し込みます。

#### リクエスト

**Content-Type:** `application/json`

**ボディ（Recall.ai の `transcript.data` Webhook ペイロード）:**

```json
{
  "event": "transcript.data",
  "data": {
    "bot_id": "bot_abc123",
    "data": {
      "speaker": "田中 太郎",
      "words": [
        "この",
        "仕様は"
      ]
    }
  }
}
```

**フィールド説明:**

| フィールド | 型 | 説明 |
|---|---|---|
| `event` | string | イベント種別。`transcript.data` のみ処理する。それ以外は無視して `200 OK` を返す |
| `data.bot_id` | string | Recall.ai のボット ID。`meeting_id` として利用する |
| `data.data.speaker` | string | 発言者の表示名（日本語可） |
| `data.data.words` | array of string | 文字起こし済み単語のリスト。スペース区切りで結合して `text` を組み立てる |

#### レスポンス

| ステータス | 条件 |
|---|---|
| `202 Accepted` | 正常受信・処理開始 |
| `200 OK` | 処理スキップ（`transcript.data` 以外のイベント、空 words、空テキスト） |
| `400 Bad Request` | JSON パース失敗（aiohttp が自動で返す） |

#### 内部処理フロー

```
POST /api/recall/transcript
    │
    ├─ event ≠ "transcript.data" → 200 OK（無視）
    │
    ├─ words が空 → 200 OK（無視）
    │
    ├─ words[*].text を結合 → text（strip 後に空 → 200 OK）
    │
    ├─ Utterance を生成
    │    meeting_id  = data.bot_id
    │    speaker_id  = speaker_name.replace(" ", "-")  ※非ASCII保持
    │    speaker_name = data.data.speaker
    │    text        = words[*].text を " " で結合
    │
    ├─ Cosmos DB に utterance を保存（cosmos が設定されている場合）
    │    ※ 保存失敗しても後続処理は継続する
    │
    ├─ Orchestrator.process(utterance) を呼び出す
    │    ※ 例外が発生しても 202 を返す（Recall.ai のリトライストームを防ぐ）
    │
    └─ 202 Accepted
```

#### `speaker_id` の導出ルール

Recall.ai は安定した speaker ID を提供しないため、`speaker_name` から導出します。

```
"田中 太郎"  →  "田中-太郎"
"John Smith" →  "John-Smith"
```

スペースをハイフンに変換するだけで、日本語・英語などの非 ASCII 文字はそのまま保持します。

---

## Recall.ai の設定手順

### 1. Webhook URL の確認

Terraform で本番環境をデプロイ後、以下のコマンドで Webhook URL を取得します。

```bash
cd infra
terraform output recall_webhook_url
```

出力例:
```
"https://mochikiki-bot-dev.wonderfulbeach-xxxxxxxx.japaneast.azurecontainerapps.io/api/recall/transcript"
```

### 2. Recall.ai ダッシュボードでの設定

1. [Recall.ai ダッシュボード](https://www.recall.ai/) にログインする
2. **Settings > Webhooks** を開く
3. **Add Webhook** をクリックする
4. 以下を設定する:

   | 項目 | 値 |
   |---|---|
   | URL | `terraform output recall_webhook_url` の値 |
   | Events | `transcript.data` にチェックを入れる |

5. **Save** をクリックする

### 3. Recall.ai ボットを Teams 会議に参加させる

Recall.ai API を使ってボットを会議に参加させます。

```bash
curl -X POST https://us-east-1.recall.ai/api/v1/bot \
  -H "Authorization: Token YOUR_RECALL_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "meeting_url": "https://teams.microsoft.com/l/meetup-join/...",
    "bot_name": "MOCHI-kiki 文字起こしボット",
    "transcription_options": {
      "provider": "assembly_ai"
    }
  }'
```

レスポンスに含まれる `id` が `bot_id` となり、そのまま `meeting_id` として利用されます。

---

## ローカル開発での動作確認

### サーバーの起動

```bash
python -m src.main
```

サーバーが起動すると以下のログが表示されます:
```
INFO:src.main:Bot サーバー起動: port 3978
```

### curl でエンドポイントをテストする

```bash
curl -X POST http://localhost:3978/api/recall/transcript \
  -H "Content-Type: application/json" \
  -d '{
    "event": "transcript.data",
    "data": {
      "bot_id": "bot_test001",
      "data": {
        "speaker": "田中 太郎",
        "words": ["この", "仕様は", "正しいですか"]
      }
    }
  }'
```

期待レスポンス: `HTTP 202`

### スキップされるケースのテスト

**対象外イベント（`200 OK` が返る）:**

```bash
curl -X POST http://localhost:3978/api/recall/transcript \
  -H "Content-Type: application/json" \
  -d '{"event": "bot.status_change", "data": {}}'
```

**空の words（`200 OK` が返る）:**

```bash
curl -X POST http://localhost:3978/api/recall/transcript \
  -H "Content-Type: application/json" \
  -d '{
    "event": "transcript.data",
    "data": {
      "bot_id": "bot_test001",
      "data": {"speaker": "田中 太郎", "words": []}
    }
  }'
```

---

## ログの確認

### ローカル

サーバーのコンソールに直接出力されます。`utterance_id` でトレースできます。

```
INFO:src.api.recall_router: (utterance_idは出力しない — 正常系はログなし)
ERROR:src.api.recall_router:orchestrator.process() failed for utterance utt_xxxx
Traceback (most recent call last):
  ...
```

### Azure Container Apps（本番）

Log Analytics Workspace でクエリします。

```kql
ContainerAppConsoleLogs
| where ContainerName == "bot"
| where Log contains "recall_router"
| order by TimeGenerated desc
| take 50
```

---

## 認証

現時点では Webhook 署名検証は実装していません（ハッカソン用デモスコープ）。

本番運用時は Recall.ai の `X-Recall-Signature` ヘッダーを使った HMAC 検証を追加予定です。追加する場合も `RecallWebhookRouter` クラスのインターフェースは変更しません。

---

## トラブルシューティング

| 症状 | 原因 | 対処 |
|---|---|---|
| Recall.ai が Webhook を送っても `202` が返らない | URL が間違っている | `terraform output recall_webhook_url` で正しい URL を確認する |
| Orchestrator が処理しない | `meeting_id`（`bot_id`）に対応する会議参照が登録されていない | Teams Bot が先に会議チャットに参加し `register_meeting()` を呼ぶ必要がある |
| Cosmos に保存されない | Cosmos DB の接続情報が正しくない | Key Vault のシークレットと環境変数を確認する |
| `400 Bad Request` が返る | リクエストボディが正しい JSON でない | `Content-Type: application/json` ヘッダーを確認する |
| ログに `cosmos.save_utterance() failed` が出る | Cosmos DB への書き込み失敗 | Orchestrator の処理は継続するが、発話ログが欠落する。接続情報を確認する |
