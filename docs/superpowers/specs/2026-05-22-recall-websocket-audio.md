# Recall.ai WebSocket — Real-time Audio (and Transcript) Receiver

**Date:** 2026-05-22
**Author:** MOCHI-kiki Team
**Status:** Draft → Ready for Implementation

---

## 0. Executive Summary

会議音声を Recall.ai から **WebSocket でリアルタイム受信**する経路を追加する。現状の HTTPS Webhook (`transcript.data` のみ受信、確定文字起こしテキストのみ) では：

- Recall 側で確定 (`is_final`) するまで待ちが入りレイテンシが大きい
- 生音声を自前で扱えないため、Azure AI Speech 等の社内 ASR / カスタム話者識別 / リアルタイム要約への組み込みが不可能
- 部分 transcript (`transcript.partial_data`) や参加者イベントを取りこぼす

WebSocket 経路では：

- `audio_mixed_raw.data` で **16 kHz / mono / S16LE PCM** の生音声を base64 envelope で連続受信できる
- 同じ接続で `transcript.data` / `participant_events.*` も購読できる（v1.11）
- 接続単位で bot を識別できるため、bot↔meeting マッピングのプロセス内 dict 依存（現状の最大運用リスク）を解消できる

**スコープ**：今回は **生音声 (`audio_mixed_raw.data`)** の受信パイプラインを主目的とする。`transcript.data` も同じハンドラで処理し、既存 Webhook 経路と置換可能とする。Azure AI Speech への接続は I/F のみ定義し、本実装は本 spec の非ゴール。

---

## 1. Goals / Non-Goals

### Goals
1. Recall.ai が `wss://<our-host>/api/recall/ws` に張ってくる WebSocket を aiohttp で受け、`audio_mixed_raw.data` の PCM を非同期キューに流す。
2. 同じ WS で `transcript.data` も受け、既存 `Utterance → Cosmos → Orchestrator` パイプラインに従来どおり投入する。
3. Recall ↔ MOCHI-kiki 間の **Svix 互換 HMAC-SHA256 署名検証** を Upgrade ハンドシェイク時に行う（payload が空のため `${id}.${ts}.` を署名対象とする）。
4. bot 投入時に `realtime_endpoints` を WebSocket 型で送信できるよう `RecallBotClient` を拡張。Config で `webhook | websocket | both` を切り替えられる。
5. 接続単位で `bot.id` をハンドラ内部状態として保持し、メッセージごとに毎回 lookup する。bot 終了で接続が閉じる前提で `_bot_to_meeting` プロセス内 dict 依存度を下げる。
6. 既存 Webhook 経路を**並走**させ、フィーチャーフラグでロールバック可能。

### Non-Goals
- Azure AI Speech / Whisper / 他 ASR への音声フィード本実装（I/F のみ）
- 話者ダイアライゼーション（`audio_separate_raw.data` 経路）
- 録画ファイル (`video_*`) 受信
- Recall.ai Desktop SDK のリアルタイム署名検証（公式が limited support と明記）
- マルチレプリカ対応における WS スティッキー化（後続 spec）

---

## 2. 公式仕様の確定情報（2026-05-22 時点 / Recall API v1.11）

| 項目 | 値 / ソース |
|---|---|
| WS スキーム | `wss://` 必須（推奨）。`ws://` 可だが本番禁止 |
| 接続方向 | **Recall がクライアント、我々がサーバ** |
| URL 形式 | bot 作成時 `recording_config.realtime_endpoints[].url` に指定 |
| 同時接続 | 各 realtime endpoint が独立した WS を張る。bot 単位 |
| 認証方式 | (A) Workspace secret による HMAC-SHA256 署名 (Upgrade 時ヘッダ) / (B) クエリトークン `?token=...` |
| 署名対象 | `${webhook-id}.${webhook-timestamp}.${body}` （WS Upgrade は body 空） |
| 署名ヘッダ | `webhook-id` (or `svix-id`), `webhook-timestamp` (or `svix-timestamp`), `webhook-signature` (or `svix-signature`) |
| リトライ | 接続失敗時最大 **30 回、固定 3 秒間隔**。30 回失敗で endpoint が `failed` |
| 推奨 keep-alive | 30 秒ごとの ping（アイドル切断対策） |
| 音声フォーマット | `audio_mixed_raw.data`: 16 kHz / mono / **S16LE 16-bit PCM** / base64 文字列 |
| 1 バイトあたり音声長 | 2 byte ≈ 1 sample ≈ 62.5 µs。32 byte ≈ 1 ms |
| メッセージ envelope | JSON テキストフレーム（後述） |
| 1 endpoint 複数イベント | v1.11 から OK（`events: [...]` に複数指定）|

### 2.1 メッセージ envelope（audio_mixed_raw.data）

```json
{
  "event": "audio_mixed_raw.data",
  "data": {
    "data": {
      "buffer": "<base64 S16LE PCM 16kHz mono>",
      "timestamp": {
        "absolute": "2026-05-22T03:14:15.123Z",
        "relative": 12.345
      }
    },
    "realtime_endpoint": { "id": "rte_xxx", "metadata": {} },
    "audio_mixed":       { "id": "amx_xxx", "metadata": {} },
    "recording":         { "id": "rec_xxx", "metadata": {} },
    "bot":               { "id": "bot_xxx", "metadata": {} }
  }
}
```

### 2.2 メッセージ envelope（transcript.data — WS 経路でも同形）

```json
{
  "event": "transcript.data",
  "data": {
    "data": {
      "words": [
        {"text": "この", "start_timestamp": {"relative": 0.0}, "end_timestamp": {"relative": 0.3}},
        {"text": "仕様は", "start_timestamp": {"relative": 0.3}, "end_timestamp": {"relative": 0.7}}
      ],
      "is_final": true,
      "language_code": "ja",
      "participant": {"id": 1, "name": "田中 太郎", "is_host": false}
    },
    "transcript": { "id": "trn_xxx", "metadata": {} },
    "recording":  { "id": "rec_xxx", "metadata": {} },
    "bot":        { "id": "bot_xxx", "metadata": {} }
  }
}
```

これは既存 `RecallWebhookHandler._handle_transcript` が処理する形と**ほぼ同形**（既存も `data.data.is_final` / `data.data.words[*].text` / `data.bot.id` を見ている）。WS でも再利用できる。

---

## 3. アーキテクチャ

```
                    ┌──────────────────────────────────────────────────┐
                    │                    Teams 会議                     │
                    │  ┌──────────────────────────┐                    │
                    │  │  Recall.ai bot (joined)  │                    │
                    │  └──────────┬───────────────┘                    │
                    └─────────────┼────────────────────────────────────┘
                                  │ wss connection (Recall is client)
                                  │ events:
                                  │   audio_mixed_raw.data
                                  │   transcript.data
                                  ▼
   ┌────────────────────────────────────────────────────────────────┐
   │ MOCHI-kiki aiohttp server (port 3978)                          │
   │                                                                │
   │  GET /api/recall/ws  ── verify Svix sig on Upgrade  ──┐        │
   │                                                       │        │
   │                          ┌────────────────────────────┘        │
   │                          ▼                                      │
   │   RecallWsHandler (per-connection)                              │
   │     - state: bot_id (from first msg)                            │
   │     - state: meeting_id (lookup from bot_id ↔ Cosmos meetings)  │
   │     - async for msg in ws:                                      │
   │         dispatch(event)                                         │
   │            ├─ audio_mixed_raw.data → AudioSink.push(pcm, ts)    │
   │            ├─ transcript.data      → existing pipeline          │
   │            └─ unknown              → log INFO                   │
   │                                                                 │
   │   AudioSink (in-memory pluggable interface)                     │
   │     - NoopAudioSink   (default; spec scope ends here)           │
   │     - <future> AzureSpeechSink                                  │
   │     - <future> FileDumpSink (debug)                             │
   └────────────────────────────────────────────────────────────────┘
```

### 3.1 接続ライフサイクル

1. **bot 作成** (`POST /api/v1/bot`)
   - `recording_config.realtime_endpoints` に `{type: "websocket", url: <our wss>, events: [...]}` を指定
2. **HTTP Upgrade**
   - Recall が `GET /api/recall/ws` に Upgrade リクエスト
   - 我々は `Svix` ヘッダで HMAC-SHA256 を検証 → NG なら **101 を返さず 401**
3. **WS established**
   - Recall は基本的に「サーバへ流すだけ」。ack 不要
   - 最初の 1〜2 メッセージで `bot.id` が判明 → ハンドラ内 `bot_id` を確定し Cosmos の `meetings` から `meeting_id` を解決
4. **メッセージループ**
   - JSON テキストフレーム。バイナリは想定しないが受信したらログ + drop
   - `event` で分岐
5. **クローズ**
   - Recall が `done` / `call_ended` 等で切断
   - 我々はクライアント切断を `WSMsgType.CLOSE / CLOSED / ERROR` で検知し、AudioSink を flush して終了

### 3.2 認証

**採用方式：A (Svix 互換 HMAC) を第一選択、B (token) は dev / fallback**

理由：
- 既存 `RecallWebhookHandler._verify_request` の secret 管理・rotation 運用がそのまま使える
- Recall は workspace secret 1 本で webhook / WebSocket 共通に検証可能と公式に明記
- token 方式は URL ログ漏洩リスクが高い

```python
# pseudo
def verify_upgrade(req: web.Request) -> bool:
    msg_id  = req.headers.get("webhook-id") or req.headers.get("svix-id", "")
    msg_ts  = req.headers.get("webhook-timestamp") or req.headers.get("svix-timestamp", "")
    msg_sig = req.headers.get("webhook-signature") or req.headers.get("svix-signature", "")
    if not (msg_id and msg_ts and msg_sig): return False
    if not msg_ts.isdigit(): return False
    if abs(time.time() - int(msg_ts)) > 300: return False  # replay window
    signed = f"{msg_id}.{msg_ts}.".encode()  # body is empty on Upgrade
    expected = base64.b64encode(hmac.new(secret, signed, hashlib.sha256).digest()).decode()
    for token in msg_sig.split():
        scheme, _, sig = token.partition(",")
        if scheme == "v1" and hmac.compare_digest(sig, expected):
            return True
    return False
```

### 3.3 状態管理 (bot↔meeting マッピング)

**現状 Webhook**：`RecallWebhookHandler._bot_to_meeting: dict[str,str]`（プロセス内、レプリカ間で不整合）

**WS 経路**：
- 接続単位で `bot.id` を 1 度だけ解決すれば良いので、毎メッセージで dict 参照する必要がない
- 解決ソース優先順位：
  1. `RecallWebhookHandler.register_bot` 経由のインメモリ (= 同レプリカで bot 投入 → WS 受信した場合)
  2. **Cosmos の `meetings` コンテナで `recall_bot_id` 検索**（マルチレプリカ耐性のため新設）
- どちらも失敗 → 接続を **policy violation (1008)** でクローズ

`MeetingBot._start_recall_bot` が `meeting.recall_bot_id = bot_id` を保存しているので、Cosmos 検索の足場はある。`CosmosClient.find_meeting_by_recall_bot_id` を新規追加する（spec 範囲）。

### 3.4 AudioSink プラグイン I/F

```python
class AudioSink(Protocol):
    async def on_open(self, meeting_id: str, bot_id: str, sample_rate: int) -> None: ...
    async def push(self, meeting_id: str, pcm_bytes: bytes, *,
                   absolute_ts: str, relative_ts: float) -> None: ...
    async def on_close(self, meeting_id: str, reason: str) -> None: ...
```

本 spec では `NoopAudioSink` のみ提供。`AzureSpeechSink` 実装は別 spec（FT-RECALL-WS-AZURE-ASR）で扱う。

### 3.5 バックプレッシャ / レート制限

- 16 kHz mono S16LE = **32 kB/s per bot**
- 1 接続あたりキュー上限 1 MB（= 約 31 秒分）。`asyncio.Queue(maxsize=...)` で制御
- キュー full → 古いフレームを **drop し WARN ログ**（音声は遅延配信に意味がない）
- `audio_mixed_raw.data` 1 メッセージあたり Recall の典型送信間隔は 100-200 ms ≒ 3.2-6.4 kB

### 3.6 DoS / 入力検証

| 項目 | 上限 |
|---|---|
| 単一 JSON フレーム長 | 1 MiB (= 約 30 秒分 PCM の base64) |
| base64 デコード後 | 1.5 MiB |
| 1 接続の総バイト数 | 24h × 32 kB/s ≒ 2.6 GB（タイムアウトで切断、合算上限は付けない） |
| 接続あたり開店時間 | 24h で自動切断（運用上の安全弁） |
| サーバ全体の同時 WS 接続 | レプリカあたり 100（同時会議想定の余裕） |

---

## 4. API 詳細

### 4.1 新規エンドポイント

| メソッド | パス | 用途 |
|---|---|---|
| GET (Upgrade) | `/api/recall/ws` | Recall.ai からの realtime WebSocket |

### 4.2 既存エンドポイント変更

| パス | 変更 |
|---|---|
| `POST /api/recall/webhook` | 維持（current）。`transcript.data` のみ |
| `POST /api/recall/transcript` | **本 spec 範囲では deprecation コメントを付けるのみ**、実削除は移行計画後 |

### 4.3 Config (env) 追加

| env | デフォルト | 説明 |
|---|---|---|
| `RECALL_TRANSPORT` | `webhook` | `webhook` / `websocket` / `both`。bot 投入時の `realtime_endpoints` の組み立てを決定 |
| `RECALL_WS_PUBLIC_URL` | (未設定) | `wss://...` 必須 (`websocket`/`both` 時)。Recall に渡す自分の WS URL |
| `RECALL_AUDIO_EVENTS` | `audio_mixed_raw.data,transcript.data` | カンマ区切り。WS 経路で購読するイベント名 |
| `RECALL_WS_MAX_FRAME_BYTES` | `1048576` | 単一 WS テキストフレーム上限 |
| `RECALL_WS_QUEUE_MAX_BYTES` | `1048576` | AudioSink 行きキューの最大バイト数 |
| `RECALL_AUDIO_SINK` | `noop` | `noop` / `file` / `azure_speech`（将来）|

`webhook` モードでは現状互換（後方互換のためデフォルト）。

### 4.4 `RecallBotClient._build_create_body` 変更

```python
def _build_create_body(self, meeting_url: str) -> dict:
    endpoints = []
    if self._transport in ("webhook", "both"):
        endpoints.append({
            "type": "webhook",
            "url": self._webhook_url,
            "events": ["transcript.data"],
        })
    if self._transport in ("websocket", "both"):
        endpoints.append({
            "type": "websocket",
            "url": self._ws_url,
            "events": list(self._ws_events),
        })
    return {
        "meeting_url": meeting_url,
        "bot_name": self._bot_name,
        "recording_config": {
            "transcript": {
                "provider": {"recallai_streaming": {"language_code": self._language_code}},
                "diarization": {"use_separate_streams_when_available": True},
            },
            "audio_mixed_raw": {} if "audio_mixed_raw.data" in self._ws_events_flat else None,
            "realtime_endpoints": endpoints,
        },
    }
```

`audio_mixed_raw: {}` は **WS で `audio_mixed_raw.data` を購読する場合のみ必要**（公式仕様）。`None` キーは出力前に除去する。

---

## 5. コンポーネント

### 新規

| ファイル | 役割 |
|---|---|
| `src/api/recall_ws_router.py` | `RecallWsRouter` — GET ハンドラ + Upgrade 認証 + メッセージループ |
| `src/transcript/recall_ws_handler.py` | `RecallWsHandler` — 接続ライフサイクル、イベント分岐、状態 |
| `src/transcript/audio_sink.py` | `AudioSink` Protocol + `NoopAudioSink` |
| `src/storage/cosmos_client.py` への追加 | `find_meeting_by_recall_bot_id(bot_id) -> Optional[str]` |
| `tests/test_recall_ws_handler.py` | 単体テスト（イベント分岐、認証） |
| `tests/test_recall_ws_router.py` | 統合テスト（aiohttp test client で WS 接続） |
| `tests/test_recall_client_ws.py` | `RecallBotClient` の WS body 組み立て |

### 改修

| ファイル | 変更 |
|---|---|
| `src/config.py` | `recall_transport` / `recall_ws_public_url` / `recall_ws_events` / `recall_audio_sink` / etc. |
| `src/transcript/recall_client.py` | `transport` / `ws_url` / `ws_events` パラメタ追加、`_build_create_body` 改修 |
| `src/bot/app.py` | `recall_ws_router` を受けて `app.router.add_get("/api/recall/ws", ...)` を登録 |
| `src/main.py` | Config から WS ハンドラ組み立て、bot へ注入 |
| `infra/outputs.tf` | `recall_ws_url` 出力追加（`wss://...` 形式） |
| `docs/api-server.md` | WS エンドポイント節を追加 |

---

## 6. データフロー

### 6.1 音声フレーム

```
Recall envelope (JSON text frame)
  ─ base64 decode → bytes (raw S16LE 16kHz mono PCM)
  ─ split into 20ms chunks (= 640 bytes) before sink.push? ── ← 仕様としては「そのまま push」
  ─ await sink.push(meeting_id, pcm, absolute_ts=..., relative_ts=...)
  ─ on Queue full → drop oldest, log WARN once per N drops
```

判断：**Recall から来た PCM を分割せずそのまま `sink.push` に渡す**。チャンク分割は Sink 実装側の責務（Azure Speech は 20ms 〜 100ms 推奨だが、ライブラリが内部でバッファ）。

### 6.2 Transcript フレーム

```
Recall envelope (JSON text frame, event=transcript.data)
  ─ data.data.is_final が True のみ採用（現状と同じ規約）
  ─ data.data.words[*].text を join → text
  ─ data.data.participant.name → speaker_name
  ─ data.data.participant.id → speaker_id（int を str() 化）
  ─ Utterance.new(...) → cosmos.save_utterance → on_utterance(orchestrator.process)
```

既存 `RecallWebhookHandler._handle_transcript` のロジックを **共通化して両方から呼べる関数**にリファクタする（ハンドラ間の重複防止）。

### 6.3 エラーハンドリング

| 事象 | 挙動 |
|---|---|
| 認証ヘッダなし | 401 + 接続拒否 |
| 認証ヘッダ不正 | 401 |
| 認証 OK だが bot_id 解決不可 | WS は accept してから **policy violation (1008)** でクローズ |
| JSON パース失敗 | 単一メッセージ無視 + WARN（接続は維持） |
| 未知 event | INFO ログのみ |
| base64 デコード失敗 | 単一メッセージ無視 + WARN |
| Sink push 例外 | EXCEPTION ログ + 単一メッセージ無視（接続は維持） |
| Recall 切断 | normal close ハンドリング |
| 我々のサーバが落ちる | Recall が 30 回 / 3 秒 backoff で再接続を試みる |

---

## 7. セキュリティ

| 項目 | 対応 |
|---|---|
| 認証 | Svix HMAC-SHA256（既存 webhook と同じ secret） |
| リプレイ | `webhook-timestamp` を 5 分窓で検証 + `webhook-id` LRU で重複検知 |
| 入力サイズ | 単一 frame 上限 / base64 size 上限 |
| 個人情報 | PCM 自体は機微。ログには base64 を出さない、サイズと相対 ts のみ |
| TLS | `wss` のみ受け入れ。Container Apps は ingress で TLS 終端 |
| insecure_mode | `RECALL_WEBHOOK_INSECURE=true` は dev only。WS でも同じフラグを共通化 |
| DoS | レプリカあたり同時 WS 接続上限 100、frame size 上限、idle 30s ping |

---

## 8. 観測可能性

| 指標 | 出し方 |
|---|---|
| 接続開始 / 終了 | `RecallWsHandler: connected bot=... meeting=...` / `disconnected reason=...` |
| 受信メッセージ数 / バイト数 | 接続クローズ時にサマリ log |
| イベント別カウント | INFO ログ + 後続で Application Insights カスタムメトリクスに昇格 |
| 認証失敗 | WARN（IP は出すが secret 関連は出さない） |
| Sink push 失敗率 | ERROR ログ + 接続クローズ時サマリ |

`utterance_id` で既存ログとひも付け可能。

---

## 9. テスト戦略

| レイヤ | 内容 |
|---|---|
| Unit: 認証 | `RecallWsHandler.verify_upgrade` の HMAC 検証パターン網羅（既存 webhook テスト構造を再利用） |
| Unit: イベント分岐 | mock WS message を流し、`audio_mixed_raw.data` / `transcript.data` / 未知 で正しい関数が呼ばれる |
| Unit: bot_id 解決 | (1) インメモリ hit (2) Cosmos fallback hit (3) どちらも miss で 1008 クローズ |
| Unit: AudioSink | `NoopAudioSink` 動作、push 例外時の handler 復旧 |
| Unit: バックプレッシャ | 大量メッセージ流入でキュー上限到達 → drop、WARN 出力 |
| Integration | `aiohttp.test_utils.TestServer` で実 WS 接続、署名つき Upgrade → メッセージ受信 → close |
| Bot client | `transport=websocket` 設定で `realtime_endpoints` JSON が正しく組み立てられる |
| Regression | 既存 Webhook テスト群が全て通る |

---

## 10. パフォーマンス見積

| 項目 | 値 |
|---|---|
| 1 bot あたり帯域 | 32 kB/s (audio) + < 1 kB/s (transcript) ≒ 33 kB/s ≒ 264 kbps |
| 同時 10 bot | 0.33 MB/s ≒ 2.6 Mbps |
| メモリ / 接続 | キュー上限 1 MB + 状態 KB オーダー ≒ 1.5 MB |
| 10 同時接続 | ≒ 15 MB |
| CPU | base64 decode は 1 frame あたり µs オーダー。レプリカ vCPU 0.5 で余裕 |

Container Apps の現リソース設定で問題なし（spec 範囲では追加スケール不要）。

---

## 11. ロールアウト戦略（詳細は別途 plan ドキュメント）

1. WebSocket 経路を実装し、`RECALL_TRANSPORT=webhook` がデフォルトでデプロイ
2. dev 環境で `RECALL_TRANSPORT=both` に切り替え、両経路同時受信を検証
3. dev 環境で `RECALL_TRANSPORT=websocket` 単独運用 → 1 週間モニタ
4. prod へ `both` でロールアウト → 1 週間 → `websocket` へ
5. `RECALL_TRANSPORT=webhook` 廃止 + `recall_router.py`（簡易版）削除

---

## 12. オープン項目（実装時に解決）

- [ ] Cosmos `meetings` コンテナの `recall_bot_id` 検索クエリのパーティション設計確認（現状 `id` がパーティションキーなら cross-partition になる）
- [ ] `webhook-id` / `svix-id` どちらが Recall.ai が実際に送るか、実トラフィックで確定（コードは両方サポート）
- [ ] `events` パラメタに `transcript.partial_data` を含めるか（B 案）
- [ ] AudioSink Protocol を完全に固めるのは Azure ASR spec 開始時に再評価

---

## 13. 参考資料

- [Real-Time Websocket Endpoints — Recall.ai docs](https://docs.recall.ai/docs/real-time-websocket-endpoints)
- [How to get Mixed Audio (real-time)](https://docs.recall.ai/docs/how-to-get-mixed-audio-real-time)
- [Real-Time Endpoints (overview)](https://docs.recall.ai/docs/real-time-endpoints)
- [Real-Time Audio Protocol (v1.10 legacy)](https://docs.recall.ai/v1.10/docs/real-time-audio-protocol)
- [Authenticating Requests from Recall.ai](https://docs.recall.ai/docs/authenticating-requests-from-recallai)
- [recallai/real-time-event-starter-kit](https://github.com/recallai/real-time-event-starter-kit)
