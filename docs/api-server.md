# MOCHI-kiki API サーバー利用マニュアル

## サーバー情報

| 項目 | 値 |
|---|---|
| **ベース URL（本番）** | `https://mochikiki-bot-dev--0000001.orangeglacier-d7a5339f.japaneast.azurecontainerapps.io` |
| **ベース URL（ローカル）** | `http://localhost:3978` |
| **リージョン** | Japan East |
| **プラットフォーム** | Azure Container Apps |

---

## 概要

MOCHI-kiki の API サーバーは既存の Bot Framework サーバー（port 3978）に統合されています。Teams Bot としての動作に加え、外部サービスからの Webhook を受け付けるエンドポイントを提供します。

現在提供しているエンドポイント:

| メソッド | パス | 完全 URL（本番） | 用途 |
|---|---|---|---|
| `GET` (Upgrade) | `/api/recall/ws` | `wss://mochikiki-bot-dev--0000001.orangeglacier-d7a5339f.japaneast.azurecontainerapps.io/api/recall/ws` | **Recall.ai realtime WebSocket** — 生音声 (S16LE/16kHz/mono PCM) と確定 transcript を購読する経路 (推奨) |
| `POST` | `/api/recall/webhook` | `https://mochikiki-bot-dev--0000001.orangeglacier-d7a5339f.japaneast.azurecontainerapps.io/api/recall/webhook` | Recall.ai webhook (HMAC 署名検証あり、`transcript.data` のみ) |
| `POST` | `/api/recall/transcript` | `https://mochikiki-bot-dev--0000001.orangeglacier-d7a5339f.japaneast.azurecontainerapps.io/api/recall/transcript` | **Deprecated** — 旧簡易版 Webhook (Phase 6 で削除予定) |
| `POST` | `/api/messages` | `https://mochikiki-bot-dev--0000001.orangeglacier-d7a5339f.japaneast.azurecontainerapps.io/api/messages` | Bot Framework の Teams メッセージを受信する（Bot Framework 内部） |

---

## エンドポイント詳細

### `GET /api/recall/ws` (WebSocket Upgrade) — **推奨経路**

Recall.ai が会議に投入した bot から **realtime WebSocket** で接続してくる。`audio_mixed_raw.data` (生音声 PCM) と `transcript.data` を同一接続で購読する。

#### 接続方向
- **Recall がクライアント、本サーバがサーバ**。bot 作成時 (`POST /api/v1/bot`) の `recording_config.realtime_endpoints[].url` に上記 `wss://` URL を指定する。

#### 認証 (Upgrade ハンドシェイク時)
| ヘッダ | 値 |
|---|---|
| `webhook-id` (or `svix-id`) | メッセージ ID |
| `webhook-timestamp` (or `svix-timestamp`) | Unix epoch 秒 |
| `webhook-signature` (or `svix-signature`) | `v1,<base64(HMAC-SHA256(secret, "{id}.{ts}."))>` |

- Workspace secret は Recall.ai ダッシュボードの **API Keys** ページで発行し、`RECALL_WEBHOOK_SECRET` env (Key Vault) として注入する。
- Upgrade の body は空のため、署名対象は `"{id}.{ts}."` のみ。
- 検証 NG なら **401**、リプレイ (5 分超過 / 重複 `id`) も 401。

#### 購読イベント (Config `RECALL_WS_EVENTS`)
| event | 用途 |
|---|---|
| `audio_mixed_raw.data` | 全参加者ミックス PCM (16 kHz / mono / S16LE)、base64 で来る |
| `transcript.data` | 確定文字起こし。`is_final=true` のみ Orchestrator に流す |
| `transcript.partial_data` | 暫定 (本実装では受信のみログ出力) |
| `audio_separate_raw.data` | 話者別音声 (本実装では未対応) |
| `participant_events.*` | 参加者イベント (本実装ではログのみ) |

#### メッセージ envelope (`audio_mixed_raw.data`)
```json
{
  "event": "audio_mixed_raw.data",
  "data": {
    "data": {
      "buffer": "<base64 S16LE PCM 16kHz mono>",
      "timestamp": {"absolute": "ISO8601", "relative": 12.345}
    },
    "bot": {"id": "bot_xxx", "metadata": {}},
    "recording": {"id": "rec_xxx", "metadata": {}},
    "realtime_endpoint": {"id": "rte_xxx", "metadata": {}},
    "audio_mixed": {"id": "amx_xxx", "metadata": {}}
  }
}
```

#### メッセージ envelope (`transcript.data`)
```json
{
  "event": "transcript.data",
  "data": {
    "data": {
      "is_final": true,
      "words": [{"text": "この"}, {"text": "仕様は"}],
      "language_code": "ja",
      "participant": {"id": 1, "name": "田中 太郎", "is_host": false}
    },
    "bot": {"id": "bot_xxx", "metadata": {}},
    "transcript": {"id": "trn_xxx", "metadata": {}}
  }
}
```

#### bot ↔ meeting 解決
1. 接続後最初に `data.bot.id` を取り出す
2. (a) `RecallWebhookHandler` の in-memory マッピングを参照、ヒットすればそれを使う
3. (b) miss なら Cosmos `meetings` コンテナを `recall_bot_id` で検索（マルチレプリカ耐性）
4. (c) どちらも miss なら接続を **WebSocket close code 1008 (policy violation)** で切断

#### 再接続 / リトライ (Recall 側挙動)
- 接続失敗時 **最大 30 回 / 固定 3 秒間隔** で再試行
- 30 回失敗で endpoint が `failed` 状態になる

#### バックプレッシャ / 上限
| 項目 | デフォルト | env |
|---|---|---|
| 単一フレーム最大バイト | 1 MiB | `RECALL_WS_MAX_FRAME_BYTES` |
| 接続内ペンディングキュー上限 | 1 MiB | `RECALL_WS_QUEUE_MAX_BYTES` |
| heartbeat (ping) 間隔 | 30 s | （ハンドラ固定）|

#### 内部処理フロー
```
GET /api/recall/ws (Upgrade)
   │
   ├─ Svix HMAC 検証 NG → 401
   ├─ OK → WS established
   │
   └─ async for msg in ws:
        ├─ event=audio_mixed_raw.data
        │     base64 decode → AudioSink.push(meeting_id, pcm, ts)
        │
        ├─ event=transcript.data
        │     is_final=true → Utterance.new(...)
        │       → cosmos.save_utterance
        │       → orchestrator.process(utterance)
        │
        ├─ event=その他 → INFO ログのみ
        └─ 接続 close → AudioSink.on_close
```

#### AudioSink プラグイン (`RECALL_AUDIO_SINK`)
| 値 | 内容 |
|---|---|
| `noop` (デフォルト) | 何もしない。バイト数だけログ |
| `file` | `/tmp/mochi-kiki-audio/<meeting_id>.pcm` に追記。ffmpeg で WAV 化可能 |
| `azure_speech` | 別 spec で実装予定 (現状 `NotImplementedError`) |

---

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

### A. WebSocket 経路 (推奨)

1. **本サーバ側の env を切り替える** (Key Vault 経由で Container Apps に注入)
   | env | 値 |
   |---|---|
   | `RECALL_TRANSPORT` | `websocket` または `both` |
   | `RECALL_WS_PUBLIC_URL` | `wss://<your fqdn>/api/recall/ws` (`terraform output recall_ws_url` で取得) |
   | `RECALL_WS_EVENTS` | `audio_mixed_raw.data,transcript.data` |
   | `RECALL_AUDIO_SINK` | `noop` / `file` / (将来) `azure_speech` |
   | `RECALL_WEBHOOK_SECRET` | Recall ダッシュボード → API Keys で発行 |

2. **Recall.ai ダッシュボードでの追加設定は不要**
   - bot 作成時に `recording_config.realtime_endpoints` 配列で渡すため、ダッシュボード側にエンドポイント登録は不要
   - Workspace secret のみ事前に発行

3. **動作確認**: bot 起動後、サーバログに以下が出ることを確認
   ```
   INFO:src.transcript.recall_ws_handler:RecallWsHandler: WS established remote=...
   INFO:src.transcript.recall_ws_handler:RecallWsHandler: closed bot_id=... msgs=... audio_bytes=...
   ```

### B. Webhook 経路 (互換 / フォールバック)

```
https://mochikiki-bot-dev--0000001.orangeglacier-d7a5339f.japaneast.azurecontainerapps.io/api/recall/webhook
```

最新 URL は常に以下で確認できます:
```bash
cd infra && terraform output recall_ws_url            # 推奨: WebSocket
cd infra && terraform output recall_webhook_url       # Webhook (HMAC 検証あり)
cd infra && terraform output recall_webhook_url_legacy  # DEPRECATED: /api/recall/transcript (無認証)
```

> **⚠️ 重要**: 旧 `/api/recall/transcript` (`recall_webhook_url_legacy`) は **署名検証なし**です。`RECALL_WEBHOOK_PUBLIC_URL` 環境変数や Recall.ai ダッシュボード設定では必ず `/api/recall/webhook` 側を使ってください。

### 2. Recall.ai ダッシュボードでの設定

#### 認証用 secret の取得（必須）

1. [Recall.ai ダッシュボード](https://www.recall.ai/) にログイン
2. **API Keys** ページを開く
3. **Verification Secret** をコピー (`whsec_...` 形式)
4. Container App に `RECALL_WEBHOOK_SECRET` として登録（HMAC-SHA256 検証用、webhook / WebSocket 共通）

#### Webhook URL の登録は不要

bot 作成時の `recording_config.realtime_endpoints[]` で動的に渡すため、Recall.ai ダッシュボード側にエンドポイントを事前登録する必要はありません（`RecallBotClient` が自動付与）。

### 3. Recall.ai ボットを Teams 会議に参加させる

通常運用では、Teams 会議で `MeetingBot.on_teams_meeting_start_activity` が `RecallBotClient.create_bot` を自動で呼び出します。手動でテストする場合の API は以下：

```bash
# WebSocket 経路（推奨）
curl -X POST https://us-east-1.recall.ai/api/v1/bot \
  -H "Authorization: Token YOUR_RECALL_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "meeting_url": "https://teams.microsoft.com/l/meetup-join/...",
    "bot_name": "MOCHI-kiki",
    "recording_config": {
      "transcript": {
        "provider": {"recallai_streaming": {"language_code": "ja"}},
        "diarization": {"use_separate_streams_when_available": true}
      },
      "audio_mixed_raw": {},
      "realtime_endpoints": [
        {
          "type": "websocket",
          "url": "wss://<your fqdn>/api/recall/ws",
          "events": ["audio_mixed_raw.data", "transcript.data"]
        }
      ]
    }
  }'
```

レスポンスに含まれる `id` が `bot_id` となり、Cosmos `meetings` コンテナ `recall_bot_id` 列を介して `meeting_id` に紐付きます。

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

**ローカル:**
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

**本番（Azure）:**
```bash
curl -X POST https://mochikiki-bot-dev--0000001.orangeglacier-d7a5339f.japaneast.azurecontainerapps.io/api/recall/transcript \
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
| WS `Upgrade` が 401 になる | secret 不一致 / clock skew | `RECALL_WEBHOOK_SECRET` を確認、サーバ時刻が 5 分以内に揃っているか確認 |
| WS 接続直後に 1008 で切断 | `bot.id` から `meeting_id` 解決失敗 | `meetings` コンテナに対象 `recall_bot_id` を持つ doc があるか確認。マルチレプリカで bot 投入と WS 受信が別 pod に行った場合に発生 |
| `audio_mixed_raw.data` が来ない | `recording_config.audio_mixed_raw = {}` の付け忘れ | `RECALL_WS_EVENTS` に `audio_mixed_raw.data` を入れて再デプロイ (`RecallBotClient` が自動付与する) |
| Recall 側で endpoint が `failed` 状態 | 30 回 / 90 秒の連続接続失敗 | Container Apps の ingress / 証明書 / WS サポートを確認 |
