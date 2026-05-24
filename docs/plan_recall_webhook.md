# 実装計画: Recall.ai Webhook 受信スケルトン

## ゴール

Recall.ai が会議に投入した bot から送られる **Real-time Transcript Webhook** を MOCHI-kiki が受信し、既存の発話処理パイプライン（`Utterance` → Cosmos → Orchestrator）に流し込めるようにする。本タスクは**スケルトン**であり、Recall アカウントが用意できるまでは動作確認用のスタブとして機能する。

## 非ゴール（このタスクでやらないこと）

- Recall bot を会議に投入する API クライアント実装（`POST /api/v1/bot`）
- WebSocket（生 PCM）受信
- Azure AI Speech との統合
- 既存の Graph Subscription 経路の置き換え（共存させる）
- Recall アカウントの本契約・本番稼働
- Cosmos の保存スキーマ変更

---

## 既存規約の確認（調査結果）

| 観点 | リポジトリ規約 |
|---|---|
| Web フレームワーク | `aiohttp.web` (`src/bot/app.py`) |
| ルート登録 | `create_app_with_adapter` 内のクロージャ + `app.router.add_post(...)` |
| 既存 Webhook 前例 | `/api/notifications` (Graph 変更通知) — `validationToken` ハンドシェイク含めて実装済 |
| 発話パイプライン入口 | `MeetingBot.handle_transcript_notification(notification: dict)` |
| モデル | `@dataclass` + `to_dict()` + `Utterance.new(...)` クラスメソッド |
| 抽象 | `src/transcript/base.py::UtteranceSource` (start/stop) |
| Config | `Config.__init__` で env を読む。必須は `os.environ[]`、任意は `os.environ.get(..., default)` |
| ロガー | `logging.getLogger(__name__)` |
| テスト | `pytest` + `pytest-asyncio` (auto mode)、`AsyncMock` / `MagicMock` |
| ファイル先頭コメント | `# src/path/file.py` |

---

## 設計方針

### 全体アーキテクチャ

```
[Teams 会議]
    ↓ Recall.ai bot 参加
[Recall.ai (Svix)]
    ↓ HTTPS POST (transcript.data)
[Container Apps ingress]
    ↓
[aiohttp app] /api/recall/webhook
    ↓
[RecallWebhookHandler]
   ├─ ① 署名検証 (Svix HMAC-SHA256)
   ├─ ② イベントタイプ分岐 (transcript.data / bot.status_change ほか)
   ├─ ③ payload → Utterance 変換
   ├─ ④ Cosmos 保存
   └─ ⑤ on_utterance(utterance) コールバック
[Orchestrator] ← 既存パイプライン
```

### Recall webhook ペイロード形式（参考）

```json
{
  "event": "transcript.data",
  "data": {
    "data": {
      "words": [
        {"text": "認証フロー", "start_timestamp": {"relative": 1.23}, "end_timestamp": {"relative": 1.78}}
      ],
      "participant": {"id": 12345, "name": "田中 太郎", "is_host": false},
      "is_final": true
    },
    "bot": {"id": "550e8400-e29b-41d4-a716-446655440000"}
  }
}
```

Recall は Svix 経由でイベントを送る。**HTTP ヘッダー**:
- `svix-id`: メッセージ ID
- `svix-timestamp`: Unix epoch（秒）
- `svix-signature`: `v1,<base64(HMAC-SHA256(secret, id.timestamp.body))>` 形式（複数署名がスペース区切りで連結されることあり）

### Bot ID → meeting_id マッピング戦略

Recall のペイロードには Teams の `meeting_id` は含まれず、`bot.id` のみ。MOCHI-kiki 側で **bot.id → meeting_id のマッピング**を保持する必要がある。

**今回のスケルトンでは**:
- メモリ内 dict `_bot_to_meeting: dict[str, str]` を持つ
- 後で Recall bot 作成 API クライアント実装時に、bot 作成と同時に登録する
- 未登録 bot からの webhook は警告ログのみで 200 返却（Svix 再送ループを避ける）

### 署名検証

- env: `RECALL_WEBHOOK_SECRET`（Svix の `whsec_xxx` 形式）
- 未設定時は **fail-closed**（401 を返して受信拒否）。開発時の bypass は `RECALL_WEBHOOK_SECRET=disabled` を別途用意するか、明示的に環境変数で disable する選択肢を残す（→ 設計レビューで決める）
- リプレイ対策: `svix-timestamp` が現在時刻から ±5 分以上ずれていたら拒否
- 比較は `hmac.compare_digest` で定数時間比較
- 検証ロジックは独立した関数として切り出し、ユニットテスト可能にする

### イベントタイプの扱い

| event | 扱い |
|---|---|
| `transcript.data` (or `transcript.partial_data`) | 発話として処理。`is_final == True` のみ取り込む（partial は当面捨てる） |
| `bot.status_change` | ログのみ。`status == "done"` で `_bot_to_meeting` から削除 |
| その他 | デバッグログのみで 200 |

### エラー処理

- 署名検証失敗 → 401
- JSON パース失敗 → 400
- 未知の event → 200 (ログのみ)
- 内部処理失敗 → 500 を返さず、ログを出して 200 を返す（Svix のリトライ嵐回避）。ただし**復旧不可能なエラーは別途キューに退避するべきだが、今回は TODO コメントで明示**

### 並行性

- Webhook はリクエスト毎に独立したコルーチンで処理
- `_bot_to_meeting` の更新は単一イベントループ上なので追加の同期不要
- 重い処理（Cosmos 保存 + on_utterance 連鎖）は `asyncio.create_task` で fire-and-forget せず、現状の Graph 経路と同じく同期実行（バックプレッシャー優先）

---

## ファイル構成

| ファイル | 種別 | 目的 |
|---|---|---|
| `src/transcript/recall_source.py` | 新規 | Recall webhook 受信ハンドラ & ペイロードパーサ。`UtteranceSource` は実装しない（push 型）。`RecallWebhookHandler` クラスを公開 |
| `src/bot/app.py` | 編集 | `/api/recall/webhook` ルート追加、`recall_handler` を引数受け取る |
| `src/main.py` | 編集 | `RecallWebhookHandler` を組み立て、`create_app_with_adapter` に渡す |
| `src/config.py` | 編集 | `recall_webhook_secret` 追加 (任意、未設定なら無効化フラグを True) |
| `src/bot/teams_bot.py` | 編集（最小） | `register_recall_bot(bot_id, meeting_id)` の薄いヘルパー追加（または `RecallWebhookHandler` 内で持つ。設計レビューで決定）|
| `tests/test_recall_webhook.py` | 新規 | 署名検証 / ペイロード変換 / イベント分岐 / 未登録 bot / リプレイ / 未認証のテスト |

### `RecallWebhookHandler` の責務分割

```python
class RecallWebhookHandler:
    def __init__(
        self,
        webhook_secret: Optional[str],
        cosmos_client: CosmosClient,
        on_utterance: Callable[[Utterance], Awaitable[None]],
        clock: Callable[[], float] = time.time,   # テスト容易性
    ) -> None: ...

    def register_bot(self, bot_id: str, meeting_id: str) -> None: ...
    def unregister_bot(self, bot_id: str) -> None: ...

    async def handle(self, request: aiohttp.web.Request) -> aiohttp.web.Response:
        """エントリポイント。ルートから呼ばれる。"""

    # 内部
    def _verify_signature(self, headers, raw_body) -> bool: ...
    def _parse_transcript_event(self, payload: dict) -> Optional[Utterance]: ...
```

`UtteranceSource` インターフェースとは形が違うので継承しない（pull 型ではなく push 型のエッジ受信）。代わりに `_on_utterance` コールバックを共有することで既存パイプラインと結合する。

---

## テスト計画

| ケース | 期待 |
|---|---|
| 正常: `transcript.data` is_final=True | 200, on_utterance 1回呼ばれる, Utterance.text が正しい |
| partial: is_final=False | 200, on_utterance 呼ばれない |
| 未登録 bot からの webhook | 200, on_utterance 呼ばれない, 警告ログ |
| 署名不正 | 401 |
| 署名 OK だが timestamp が古い (>5min) | 401 |
| 不正 JSON | 400 |
| `bot.status_change status=done` | 200, register が削除される |
| secret 未設定 (fail-closed) | 全リクエスト 401 (default), または明示的 disable で 200 |
| 複数 word 連結 | text が空白区切りで正しく連結される |
| participant.name 欠落 | speaker_name = "不明" にフォールバック |

---

## セキュリティチェックリスト（実装時の自己チェック）

- [ ] 署名検証は `hmac.compare_digest` で定数時間比較
- [ ] secret は env から読み、ログに出力しない
- [ ] raw body をパース前に保持して署名検証に使う（aiohttp `await req.read()` で bytes 取得）
- [ ] timestamp リプレイ防御（±5分）
- [ ] エラー応答に内部情報を含めない
- [ ] 例外は握り潰さない（ログに残す）
- [ ] webhook の bot.id は信用するが、`bot.id → meeting_id` マッピングが無い場合はサイレント無視（不正な webhook が来てもデータ汚染しない）
- [ ] PII（参加者名・発話内容）の DEBUG ログ出力に注意（ログレベル分け）

---

## ロールアウト手順（参考、本タスク範囲外）

1. このスケルトンをマージ
2. Recall アカウント開設 + Tokyo region API key 取得 → Key Vault に `recall-webhook-secret` / `recall-api-key` 追加
3. Container Apps の env に `RECALL_WEBHOOK_SECRET` 反映
4. 別タスクで `RecallBotClient`（bot 作成 API クライアント）を実装、bot 作成時に `recall_handler.register_bot(bot.id, meeting_id)` を呼ぶ
5. ステージング会議で動作確認、Graph 経路と並行運用 → 比較検証
6. 既存 Graph 経路をフィーチャーフラグで切替可能に

---

## オープン質問（実装前に解決）

| 質問 | 暫定 |
|---|---|
| Q1. secret 未設定時のデフォルト挙動 | **fail-closed (401)**。`RECALL_WEBHOOK_INSECURE=true` を別途設ければ開発時 bypass 可。 |
| Q2. `RecallWebhookHandler` を `src/transcript/` に置くべきか `src/bot/` か | `src/transcript/` 配下。理由: 発話ストリーム源として位置づける（mock_source / graph_subscription と並列）。push 型でインターフェース不一致な点は許容 |
| Q3. `bot_to_meeting` のマッピング保管場所 | スケルトン段階ではメモリ。次フェーズで Cosmos `meetings` コンテナの追加カラムに移行 |
| Q4. partial 文字起こしの扱い | 当面捨てる。is_final のみ。ただし速報用に partial を流したいケースもあるので、後で `Utterance.is_partial` フラグ追加の余地を残す |
| Q5. webhook の重複配送対策 | Svix は at-least-once。`svix-id` を見て重複排除すべきだが、Cosmos 側の upsert で実質吸収できる。スケルトンでは TODO コメントのみ |

---

## 完了条件

- [x] スケルトンが上記ファイルに実装され、`pytest tests/test_recall_webhook.py` が pass (30/30)
- [x] `src/main.py` から `create_app_with_adapter` を呼ぶ箇所が壊れていない
- [x] サブエージェント 3 名 (security / architect / code-review) のレビュー指摘が反映済
- [ ] `docs/音声取得方式比較.md` に Recall.ai 行を追加（別タスク）

---

## 本リリース前に解決必須の事項（スケルトン範囲外、レビューで判明）

スケルトンとしては完成だが、**Recall を実運用に乗せる前**に以下を必ず解決すること。
順序付きで列挙する（上ほど重要）。

### B1. 【critical】Graph と Recall の同時稼働で utterance 重複

Graph Subscription と Recall webhook が同じ会議に対して**同時に発話を流すと Cosmos に二重書き込みされ orchestrator が二重発火する** (clarification の二重送信、要約の二重生成、コスト倍増)。

- **対策**: `Meeting.transcript_source: Literal["graph", "recall"]` を会議開始時に決定し、両ハンドラに「自分が担当の source か」をチェックさせる
- 当面 `RecallWebhookHandler` を稼働開始時に **Graph 経路を該当会議で停止する** メソッドを足す方針も可

### B2. 【high】`_bot_to_meeting` がインメモリ・単一レプリカ前提

- プロセス再起動 / Container Apps スケールアウトで mapping が失われ webhook が silent drop
- **対策**: `Meeting` ドキュメントに `recall_bot_id` フィールドを追加し、`MeetingRepository.find_by_recall_bot_id(bot_id)` で都度引く
- 当面の運用注意: **replica 数を 1 に固定**

### B3. 【high】`UtteranceSink` 抽象の不在による知識重複

`MeetingBot.handle_transcript_notification` (`teams_bot.py:71-89`) と `RecallWebhookHandler._handle_transcript` (`recall_source.py`) が「Cosmos 保存 → on_utterance」を独立に実装している。`MockUtteranceSource` は Cosmos 保存を飛ばしているという不整合もある。

- **対策**: `UtteranceSink.ingest(Utterance)` 抽象を切り、全ソースは sink にのみ依存。orchestrator は sink にコールバック登録。
- これが `main.py` の `_placeholder_on_utterance` → `set_on_utterance` リバインドの汚さも同時に解消する

### B4. 【medium】可観測性

`logger.exception` だけでは production で気付けない。

- **対策**: 401 / 400 / 重複 svix-id / 未登録 bot / dispatch 失敗 をそれぞれメトリクス化（App Insights / OpenTelemetry）
- DLQ: dispatch 失敗時は payload の安全部分（event, bot_id, svix_id）だけを別ストレージに退避

### B5. 【medium】Recall API クライアント未実装

- 本スケルトンには `register_bot()` を呼ぶ箇所がない。Recall に bot を投入する API クライアント (`POST /api/v1/bot`) を別タスクで実装し、会議開始フックから呼ぶ
- そのときに B2 の永続化と B1 の source 排他も同時に決める

### B6. 【low】WAF / IP 許可リスト

- secret が漏れた場合の最後の砦として、Recall/Svix の egress IP のみを通す reverse-proxy ルールを足す
- Recall のドキュメントから IP リストを取得する手順を ops runbook に残す

---

## 適用済みのレビュー指摘（変更履歴）

### セキュリティ (Security Engineer 指摘)

| # | 内容 | 対応 |
|---|---|---|
| S1 | base64 secret デコード時に validate=True、起動時 fail-fast | 適用 (`_decode_secret`, `RecallSecretError`) |
| S2 | 署名パース過剰許容 | 適用 (`strip().split()` + `partition`) |
| S3 | svix-id 重複 (replay) 防御 | 適用 (`_seen_svix_ids` LRU) |
| S4 | リクエストサイズ上限 | 適用 (`_MAX_REQUEST_BODY_BYTES=64KiB`, content_length 事前チェック) |
| S5 | timestamp の int パース DoS | 適用 (`_MAX_TIMESTAMP_DIGITS=16` + `isdigit`) |
| S6 | bot mapping のメモリ枯渇 | 適用 (`_MAX_BOT_MAPPINGS=10_000`) |
| S7 | logger.exception の PII | 適用 (event/svix_id のみ、payload は出さない) |
| S8 | エラー応答の情報漏洩 | 適用 (本文を空に) |
| S9 | insecure_mode の本番ガード | 適用 (`Config` で ENVIRONMENT チェック) |
| S10 | name/id の長さ・型バリデーション | 適用 (`_sanitize_text`) |
| S11 | words 件数バウンド | 適用 (`_MAX_WORDS=500`) |

### コード品質 (Code Reviewer 指摘)

| # | 内容 | 対応 |
|---|---|---|
| C1 | `_verify_request` 型ヒント | 適用 (`Mapping[str, str]`) |
| C3 | 日本語の空白挿入問題 | 適用 (`_join_words` で空文字連結) |
| C4 | private 属性直接代入 | 適用 (`set_on_utterance`, `is_bot_registered` 公開) |
| C5 | 例外を握り潰しすぎ | 適用 (KeyError/TypeError/ValueError 分離 + 包括 catch も残す) |
| C7 | terminal status 追加 | 適用 (done/fatal/call_ended/media_expired) |
| C8 | config の `or None` 冗長 | 適用 (空文字 → None 正規化を明示) |
| C10-12 | テスト網羅 | 適用 (将来 timestamp、boundary、未知 event、複数署名、`v2,*`、巨大 ts ほか追加) |
| C14 | id=None で "None" 文字列化 | 適用 (`_sanitize_text` で None → default) |
| C15 | `base64.binascii.Error` | 適用 (`binascii.Error` 直接) |
| C16 | `tuple` 型パラメータ化 | 適用 |
| C18 | main.py のコメント番号 | 適用 (1-9 に振り直し) |
| C19 | コンストラクタ引数順 | 適用 (required を先頭に) |
| C20 | 未知 event ログレベル | 適用 (`info`) |
| C21 | テストで `is_bot_registered()` を使う | 適用 |

### 設計 (Software Architect 指摘)

| # | 内容 | 対応 |
|---|---|---|
| A1 | UtteranceSink 抽象化 | **deferred (B3 として記録)** |
| A2 | dual-save 知識の重複 | **deferred (B3 として記録)** |
| A3 | bot mapping 永続化 | **deferred (B2 として記録)** + 単一レプリカ前提コメント追加 |
| A4 | init の private 代入 | 適用 (`set_on_utterance` 公開) |
| A5 | エラー粒度 | 部分適用 (例外を分類) + 残りは **B4 として記録** |
| A6 | Graph/Recall 二重発火 | **deferred (B1 として記録、critical)** |
| A7 | partial_data dead code | 適用 (`_dispatch` から削除) |
| A8 | 日本語空白挿入 | 適用 (C3 と同じ) |
