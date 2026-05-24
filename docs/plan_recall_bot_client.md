# 実装計画: Recall.ai Bot 投入クライアント

## ゴール

会議開始時に Recall.ai に bot を作成して投入し、会議終了時に bot を退出させる。受信側はすでに完成している (`docs/plan_recall_webhook.md`)。本タスクで Recall 経路の**送信側 (bot lifecycle)** を完成させる。

## 非ゴール

- Compliance/録音 bot（生 PCM）
- 過去ミーティングの再処理（join_at スケジューリングは optional に留める）
- Graph 経路の削除（後方互換維持）

---

## Recall API 仕様（調査結果）

| 操作 | Method | URL | 認証 | 成功応答 | Rate Limit |
|---|---|---|---|---|---|
| Create | POST | `https://{region}.recall.ai/api/v1/bot/` | `Authorization: Token <api_key>` | 201, body に `id` (UUID) | 120/min |
| Leave call | POST | `/api/v1/bot/{id}/leave_call/` | 同上 | 200 | 300/min |
| Delete (pre-join のみ) | DELETE | `/api/v1/bot/{id}/` | 同上 | 204 | — |

### Create body 構造（リアルタイム文字起こしを webhook で受ける場合）

```json
{
  "meeting_url": "https://teams.microsoft.com/l/meetup-join/...",
  "bot_name": "MOCHI-kiki",
  "recording_config": {
    "transcript": {
      "provider": {"recallai_streaming": {"language_code": "ja"}},
      "diarization": {"use_separate_streams_when_available": true}
    },
    "realtime_endpoints": [
      {
        "type": "webhook",
        "url": "https://<our-public-endpoint>/api/recall/webhook",
        "events": ["transcript.data"]
      }
    ]
  }
}
```

### Region

Tokyo: `ap-northeast-1`。データ所在 + レイテンシ観点で第一候補。

---

## 既存規約の確認（調査結果）

| 観点 | 既存パターン |
|---|---|
| HTTP クライアント | `aiohttp.ClientSession`（`graph_subscription.py` 参照） |
| ライフサイクルフック | `on_teams_meeting_start_activity` / `on_teams_meeting_end_activity` (`teams_bot.py:31, 60`) |
| 既存の bot リソース管理 | `self._active_subscriptions: dict[meeting_id, sub_id]` |
| Cosmos への永続化 | `Meeting` モデルに `transcript_subscription_id` を持つ |
| 認証情報 | env → Config → コンストラクタ注入 |
| エラー処理 | 既存はあまり堅牢でない（HTTP 失敗時の挙動が雑） — 本タスクでは改善 |

---

## 設計方針

### 全体フロー

```
[Teams 会議開始]
   ↓ Bot Framework: on_teams_meeting_start_activity
[MeetingBot]
   ├─ 1. meeting_url 取得（channel_data.meeting.joinUrl → fallback: Graph fetch）
   ├─ 2. RecallBotClient.create_bot(meeting_url, webhook_url) → bot_id
   ├─ 3. RecallWebhookHandler.register_bot(bot_id, meeting_id)
   ├─ 4. Meeting.recall_bot_id = bot_id を Cosmos に保存
   └─ 5. transcript_source に応じて Graph subscription も並行起動 or スキップ

[会議中]
   ↓ Recall → webhook → 既存 RecallWebhookHandler → orchestrator

[Teams 会議終了]
   ↓ on_teams_meeting_end_activity
[MeetingBot]
   ├─ 1. RecallBotClient.leave_call(bot_id) (best-effort)
   ├─ 2. RecallWebhookHandler.unregister_bot(bot_id)
   └─ 3. Graph subscription unsubscribe (transcript_source が graph/both のとき)
```

### Graph と Recall の排他制御（B1 への対応）

`transcript_source` を Config + Meeting レベルで制御。

| 値 | Graph subscribe | Recall create_bot | 用途 |
|---|---|---|---|
| `graph` | ✅ | ❌ | 現状互換、デフォルト |
| `recall` | ❌ | ✅ | Recall 移行後 |
| `both` | ✅ | ✅ | A/B 比較期間限定（**utterance 二重化注意** — Cosmos 上で同一発話の重複が出る） |

Config: `TRANSCRIPT_SOURCE`（env、未設定なら `graph`）

### meeting_url 取得戦略

Teams Bot Framework の `channel_data.meeting.joinUrl` が**ある場合**はそれを使う。
無い場合は Graph API `GET /communications/onlineMeetings/{onlineMeetingId}` で `joinWebUrl` を取得する。

スケルトンとしては:
1. `channel_data.meeting.joinUrl` を優先
2. それも `joinWebUrl` から fallback として取れる仕掛けは入れるが、**最初は channel_data 経由のみ実装し、無ければ警告ログ + Recall bot 投入をスキップ**（fail-safe で会議自体は壊さない）

### `RecallBotClient` の責務

- 純粋な HTTP クライアント
- リトライ: 5xx と 429 のみ exponential backoff（最大 3 回）
- タイムアウト: 10 秒
- Cosmos も orchestrator も知らない（疎結合）

### エラー処理ポリシー

| ケース | 挙動 |
|---|---|
| API key 未設定 | クライアント自体を作らない（None を流す） |
| meeting_url 取得失敗 | 警告ログ + Recall bot 投入スキップ（会議自体は継続） |
| create_bot HTTP 失敗 | 警告ログ + Recall 経路スキップ。Graph 経路があれば動く |
| leave_call HTTP 失敗 | 警告ログのみ。会議終了処理は継続 |
| rate limit (429) | リトライ 3 回 → 諦め |

**会議起動を Recall の失敗で巻き込まない**ことが最重要。

### Secret 管理

- env `RECALL_API_KEY` 必須（recall 経路を使う場合）
- `RECALL_REGION` (default: `us-east-1` — Recall の公式デフォルト)
- `RECALL_BOT_NAME` (default: `MOCHI-kiki`)
- `RECALL_WEBHOOK_PUBLIC_URL` 必須 — Recall に渡す自分側の公開 URL（例: `https://mochikiki-bot-dev.xxx.azurecontainerapps.io/api/recall/webhook`）
- `RECALL_TRANSCRIPT_LANGUAGE` (default: `ja`)

---

## ファイル構成

| ファイル | 種別 | 目的 |
|---|---|---|
| `src/transcript/recall_client.py` | 新規 | `RecallBotClient` (create_bot / leave_call) |
| `src/config.py` | 編集 | recall_api_key, recall_region, recall_bot_name, recall_webhook_public_url, recall_transcript_language, transcript_source |
| `src/models.py` | 編集 | `Meeting.recall_bot_id: Optional[str]` 追加 |
| `src/bot/teams_bot.py` | 編集 | `on_teams_meeting_start/end_activity` に Recall フックを追加 |
| `src/main.py` | 編集 | `RecallBotClient` 組み立て + `MeetingBot` に注入 |
| `tests/test_recall_client.py` | 新規 | HTTP モックで create_bot/leave_call/エラー/リトライ |
| `tests/test_teams_bot.py` | 編集 | start/end フックで Recall 呼ばれることのテスト |

### `RecallBotClient` のインターフェース

```python
class RecallBotClient:
    def __init__(
        self,
        api_key: str,
        region: str,
        bot_name: str,
        webhook_url: str,
        language_code: str = "ja",
        timeout_seconds: float = 10.0,
        session: Optional[aiohttp.ClientSession] = None,  # テスト用
    ) -> None: ...

    async def create_bot(self, meeting_url: str) -> Optional[str]:
        """成功時: bot.id。失敗時: None (例外は投げない)。"""

    async def leave_call(self, bot_id: str) -> bool:
        """成功/失敗を bool で返す。例外は投げない。"""

    async def close(self) -> None: ...
```

例外を投げない設計は「会議自体を壊さない」要件のため。

---

## テスト計画

| ケース | 期待 |
|---|---|
| `create_bot` 成功 | bot_id が返る、リクエスト body が期待形式 |
| `create_bot` 401 | None, 警告ログ |
| `create_bot` 429 → 200 | リトライして成功 |
| `create_bot` 5xx 3回 | None |
| `create_bot` body 検証 | meeting_url, webhook URL, language, provider が正しく入る |
| `leave_call` 200 | True |
| `leave_call` 404 | False（bot 既に削除済等） |
| `leave_call` 例外 | False、上に伝播しない |
| `MeetingBot` start で `recall_handler.register_bot` 呼ばれる | OK |
| `MeetingBot` start で `transcript_source=graph` なら Recall 呼ばない | OK |
| `MeetingBot` start で meeting_url 取得失敗 | Recall スキップ、会議は登録される |
| `MeetingBot` end で `leave_call` + `unregister_bot` 呼ばれる | OK |

---

## セキュリティチェックリスト

- [ ] API key を環境変数から、ログに出さない
- [ ] HTTP timeout 設定（無限待ち防止）
- [ ] webhook URL は HTTPS に限定（http:// を拒否）
- [ ] meeting_url は Recall に渡すだけだが、ログ出力時はマスク
- [ ] レスポンス JSON のフィールドを信用しすぎない（id の型/長さチェック）
- [ ] Cosmos に bot_id を保存する際、形式検証（UUID 形式）

---

## 完了条件

- [x] `pytest tests/test_recall_client.py` が pass (21 件)
- [x] `pytest tests/test_teams_bot.py` が pass（既存 + 追加 7 件）
- [x] Recall 失敗時に会議自体が壊れないこと（テストで担保）
- [x] サブエージェント 3 名のレビュー指摘が反映済
- [x] `transcript_source=recall` / `both` / `graph` 全てがコード上で機能すること

---

## 本リリース前に解決必須の事項（スケルトン範囲外、レビュー判明）

レビューでさらに以下が顕在化した。webhook 受信側の B1-B6 と合わせて運用前必須。

### C1. 【critical】 `both` モードは utterance 二重化を発生させる

`graph` と `recall` 両方を同時に動かす設計だが、両ハンドラが独立に `cosmos.save_utterance` と `on_utterance` を呼ぶ。

- **暫定対策**: `both` モードは **A/B 比較目的の検証期間のみ** 短期間使うルールを ops runbook に明記
- **恒久対策（要実装）**: `PrimaryTranscriptDispatcher` を導入し、`both` 中は片方を shadow（utterance_shadow コンテナへの書き込みのみ、orchestrator 起動しない）にする

### C2. 【high】 リソース漏れの恒久対策（リコンサイラ）

`_active_subscriptions` / `_active_recall_bots` がインメモリ。Container Apps 再起動 / クラッシュで mapping が失われ:
- Graph subscription は Microsoft 側で残り続ける
- Recall bot は会議に居続けて課金発生

- **対策（要実装）**: 起動時に `Meeting WHERE ended_at IS NULL` を Cosmos からスキャンし、`recall_bot_id` / `transcript_subscription_id` から in-memory dict を rehydrate するリコンサイラ
- 定期 reaper: 一定時間経過した未終了会議の bot を強制 leave_call
- Recall API の `bot.automatic_leave` を create_bot 時に指定（最大滞在時間）

### C3. 【high】 `_extract_meeting_url` の Graph フォールバック未実装

現状 `channel_data.meeting.joinUrl` のみ参照。Teams は会議種別によって joinUrl が channel_data に含まれない。

- **対策（要実装）**: Graph API `GET /communications/onlineMeetings/{onlineMeetingId}` で `joinWebUrl` を取得する `MeetingUrlResolver`
- 既存の `GraphTranscriptSubscription` と認証トークンを共有可能

### C4. 【high】 Recall webhook の transcript event レース

`create_bot` 完了 → `register_bot` 登録の間に、Recall 側から早すぎる `transcript.data` が来ると「未登録 bot」として捨てられる可能性。

- **対策**: `register_bot` を `create_bot` 呼び出し**前**に pending 状態で登録、または Recall の `bot.joining_call` イベントを待ってから transcript を受け付ける
- 実害は薄い（Recall bot の会議参加に通常数秒かかる）が、ベストプラクティスとして要対処

### C5. 【high】 401/403 が透明に隠れる

API key 間違いも transient エラーも一様に `None` を返すため、起動時に気付けない。

- **対策**: 起動時に `GET /api/v1/bot/` で 1 回 probe して fail-fast
- 401/403 検出時にサーキットブレーカーで以降の create_bot を停止しログを ERROR で発火

### C6. 【medium】 path token + IP allowlist

webhook URL が Recall 内部で扱われる以上、secret 漏洩時の最後の砦が無い。

- **対策**: `/api/recall/webhook/<32B random>` 形式の path token を導入し、secret と組で使う
- Container Apps の IP restriction で Recall egress IP のみ許可

### C7. 【medium】 MeetingBot の責務肥大

`MeetingBot` が Cosmos / Graph / Recall HTTP / Recall webhook / orchestrator / 1:1 reply を全部知っている。

- **対策**: `MeetingLifecycleService` を抽出（`start(meeting_info) -> Meeting` / `end(meeting_id)`）。`MeetingBot` は ActivityHandler の薄いシムに退化させる
- `TranscriptPipeline` インターフェース（`GraphPipeline` / `RecallPipeline` / `CompositePipeline`）でさらに分離可能

### C8. 【medium】 main.py の `bot._orchestrator` / `bot._on_utterance` mutation

construction の循環依存を private 属性代入で回避。

- **対策**: `MeetingBot.wire(orchestrator, on_utterance)` 公開メソッド or `LateBoundOrchestrator` パターン

### C9. 【medium】 `_active_meeting_by_speaker` の永続肥大

speaker → meeting の dict が cleanup されない。speaker が古い会議に発言したことになり続ける。

- **対策**: `on_teams_meeting_end_activity` で該当 meeting_id の entry を削除

---

## 適用済みのレビュー指摘

### セキュリティ
| # | 内容 | 対応 |
|---|---|---|
| S1 | region URL インジェクション | 適用 (`_ALLOWED_RECALL_REGIONS` allowlist + `_REGION_PATTERN` 二重検証) |
| S2 | duplicate-bot guard | 適用 (`_active_subscriptions`/`_active_recall_bots` 重複検知で早期 return) |
| S3 | bot 漏れ可視化 | 部分適用 (leave_call 失敗を ERROR ログ) + **defer (C2 として記録)** |
| S4 | API key / response body 漏洩 | 適用 (response body をログから除外、x-request-id のみ。例外は型名のみ) |
| S5 | meeting_url 検証 | 適用 (`_TEAMS_URL_PATTERN` + 制御文字拒否 + 長さ制限) |
| S7 | recall_client/handler 整合性 | 適用 (`MeetingBot.__init__` で raise) |
| S10 | meeting_url 長さ制限 | 適用 (2048 bytes) |
| S11 | bot_name / language バリデーション | 適用 (`_BOT_NAME_PATTERN` / `_LANGUAGE_PATTERN`) |
| S6 / S8 / S9 | path token / 401 circuit breaker / リトライ math | **defer (C5, C6 として記録)** |

### 設計
| # | 内容 | 対応 |
|---|---|---|
| A1 `both` 二重化 | **defer (C1 critical として記録)** |
| A2 MeetingBot 肥大 | **defer (C7 として記録)** |
| A3 state location | **defer (C2 として記録)** |
| A4 god object 化 | **defer (C7 として記録)** |
| A5 idempotency | 適用 (重複 start 早期 return) |
| A6 joinUrl fallback | **defer (C3 として記録)** |
| A7 visibility | 部分適用 (ERROR ログ追加) |

### コード
| # | 内容 | 対応 |
|---|---|---|
| #1 retry log 詳細 | 部分適用 |
| #2 leave_call の `is not None` | 部分適用 (`_request_with_retry` 返り値を `Optional[dict]` に絞り契約明示) |
| #3 `Optional[Any]` 型 | 適用 (`Optional[dict]`) |
| #4 404 テスト | 適用 (`len(session.calls) == 1` 追加) |
| #6 カバレッジ | 適用 (ensure_session / close / timeout-retry / list 応答 追加) |
| #7 module-level logger | 適用 |
| #8 start method 分割 | 適用 (`_start_graph_subscription` / `_start_recall_bot` 抽出) |
| #9 leave_call 失敗ログ | 適用 (ERROR ログ) |
| #10 public accessors | 適用 (`has_active_recall_bot` / `get_recall_bot_id` / `register_recall_bot`) |
| #14 `dict[str, str]` 型 | 適用 |
| その他 | 軽微なため省略 or defer |

---

## オープン質問（実装前に確定）

| 質問 | 暫定 |
|---|---|
| Q1. `transcript_source` のデフォルトは？ | `graph`（後方互換、現状動いている経路を変えない） |
| Q2. `RecallBotClient` の `session` の所有者は？ | クライアントが自前で持つ。`close()` は `main.py` の finally で呼ぶ |
| Q3. リトライ実装は外部ライブラリ？ | 標準 asyncio + 自前 backoff。tenacity 等を増やさない |
| Q4. 起動時バリデーション | `transcript_source` が `recall`/`both` のとき、recall 系 env が揃っていなければ起動失敗（fail-fast） |
| Q5. webhook URL の組み立て | `RECALL_WEBHOOK_PUBLIC_URL` を必須 env として明示。`{base}/api/recall/webhook` を組み立てるのではなく完全 URL を要求（誤組み立て事故防止） |
