# 実装・移行計画: Recall.ai WebSocket 経路 (生音声 + transcript)

**Date:** 2026-05-22
**Related Spec:** [`specs/2026-05-22-recall-websocket-audio.md`](../specs/2026-05-22-recall-websocket-audio.md)
**Owner:** MOCHI-kiki Team
**Status:** Ready

---

## 0. このプランの読み方

- **Phase 1〜3** が実装、**Phase 4〜6** が移行。
- 各 Phase の **Exit Criteria** を満たさなければ次に進まない。
- ロールバックは「フラグ 1 つで前 Phase に戻る」を全 Phase で維持。

---

## 1. ゴール / 非ゴール

### ゴール
- Recall.ai からの WebSocket 接続を `wss://<host>/api/recall/ws` で受信
- `audio_mixed_raw.data` を `AudioSink` インターフェース経由で受け渡す（実装は `NoopAudioSink` まで）
- `transcript.data` を既存パイプラインに流せる
- 既存 Webhook 経路 (`/api/recall/webhook`, `/api/recall/transcript`) と並走 → 段階的に WS 一本化
- 全ステップでロールバック可能（`RECALL_TRANSPORT` env で切替）

### 非ゴール（このプランでは触らない）
- Azure AI Speech / Whisper 等の ASR 実接続
- 話者別音声 (`audio_separate_raw.data`)
- マルチレプリカでのスティッキー WS（必要になったら別プラン）
- Recall API v1.10 legacy バイナリプロトコル対応

---

## 2. リスク一覧と対策

| # | リスク | 影響 | 対策 |
|---|---|---|---|
| R1 | Recall が送る envelope が公式ドキュメントと微妙に違う | メッセージ全部 drop | dev 環境で `RECALL_TRANSPORT=both` 期間中に実 payload をログ採取し、必要ならパース処理を補正 |
| R2 | Container Apps の WS ingress が長時間接続で切断 | 30 回 / 3 秒で Recall が再接続するが分散ログが汚れる | 30 秒 ping を実装、Container Apps `transport: HTTP/2` のリビジョン設定確認 |
| R3 | bot_id が来るまで `meeting_id` 解決できず、最初の数フレームが drop | 開幕の発話を取りこぼす | 接続開始から bot_id 解決までキューに蓄積、解決後に flush（最大 5 秒） |
| R4 | マルチレプリカで WS と bot 投入が別レプリカに着く | bot↔meeting 解決失敗で接続を 1008 close | Cosmos `meetings.recall_bot_id` を検索する `find_meeting_by_recall_bot_id` を実装し fallback |
| R5 | Svix 署名検証で `webhook-*` と `svix-*` のヘッダ違い | 全 Upgrade が 401 | 両方サポート (`headers.get(a) or headers.get(b)`) |
| R6 | 旧 `recall_router.py`（簡易版）が認証なしで残存 | 攻撃面 | Phase 6 で削除。Phase 4 〜 5 では deprecation warning ログを出す |
| R7 | `audio_mixed_raw: {}` を `recording_config` に入れ忘れ | 音声 event が来ない | Bot client 単体テストで body スナップショット検証 |
| R8 | キュー上限到達でフレーム drop | 音声欠落 | drop 発生時に WARN を 5 秒スロットルで出力、運用で検知 |
| R9 | dev / prod の secret 食い違い | prod で全部 401 | 移行時に `RECALL_WEBHOOK_SECRET` を Key Vault で共有しているか確認 |

---

## 3. Phase 1 — Skeleton と公式仕様準拠の実装（非破壊）

### 3.1 タスク

| # | 作業 | 触るファイル |
|---|---|---|
| 1.1 | `Config` に WS 関連 env 5 件追加（デフォルトで現状互換） | `src/config.py` |
| 1.2 | `AudioSink` Protocol + `NoopAudioSink` | `src/transcript/audio_sink.py` (new) |
| 1.3 | `RecallWsHandler` クラス（接続ライフサイクル + イベント分岐 + 認証） | `src/transcript/recall_ws_handler.py` (new) |
| 1.4 | `RecallWsRouter` (GET `/api/recall/ws` + Upgrade) | `src/api/recall_ws_router.py` (new) |
| 1.5 | `RecallBotClient` に `transport` / `ws_url` / `ws_events` を追加し `_build_create_body` 改修 | `src/transcript/recall_client.py` |
| 1.6 | `CosmosClient.find_meeting_by_recall_bot_id` を追加 | `src/storage/cosmos_client.py` |
| 1.7 | `RecallWebhookHandler._handle_transcript` のロジックを `transcript_pipeline.py` に抽出して WS と共有 | `src/transcript/transcript_pipeline.py` (new), `src/transcript/recall_source.py` |
| 1.8 | `app.py` に `recall_ws_router` 受け入れ口を追加（`app.router.add_get(...)`） | `src/bot/app.py` |
| 1.9 | `main.py` で Config 値から WS ハンドラ・ルータ・AudioSink を生成し注入 | `src/main.py` |
| 1.10 | `infra/outputs.tf` に `recall_ws_url` (`wss://...`) を追加 | `infra/outputs.tf` |

### 3.2 Exit Criteria
- `RECALL_TRANSPORT=webhook` で起動して**現状と全く同じ挙動**（既存テストが全部 GREEN）
- `RECALL_TRANSPORT=websocket` で起動して `/api/recall/ws` が `wss` Upgrade を受けつける
- 新規ユニットテスト（spec 9 章）が全て GREEN

### 3.3 ロールバック
- env を `RECALL_TRANSPORT=webhook` に戻して再デプロイ（コードは新しいが経路は旧）

---

## 4. Phase 2 — 単体テスト・統合テスト

### 4.1 テスト追加

| ファイル | 目的 |
|---|---|
| `tests/test_recall_ws_handler.py` | (a) Svix 検証パターン (b) event 分岐 (c) bot_id 解決 inmem/cosmos/miss (d) backpressure drop |
| `tests/test_recall_ws_router.py` | aiohttp `TestServer` で Upgrade → メッセージ送信 → close をエンドツーエンド |
| `tests/test_recall_client_ws.py` | `transport=websocket/both/webhook` での `_build_create_body` 出力スナップショット |
| `tests/test_transcript_pipeline.py` | WS / Webhook 共有ロジックの単体 |

### 4.2 Exit Criteria
- 全テスト GREEN、新規テストカバレッジ ≥ 90%（新規モジュールに対して）
- 既存 `tests/test_recall_webhook.py` 系も無修正で GREEN

---

## 5. Phase 3 — Dev デプロイと実トラフィック観察 (`both` モード)

### 5.1 手順

1. Key Vault に `RECALL_WS_PUBLIC_URL=wss://<dev fqdn>/api/recall/ws` を登録
2. dev 環境の env を `RECALL_TRANSPORT=both` に変更してデプロイ
3. Recall.ai dashboard で **追加で WebSocket endpoint を登録は不要**（bot 作成時に `realtime_endpoints` で送るため）
4. 既存 dev 会議で bot 投入 → ログを採取
   - WS 接続が立つこと
   - `audio_mixed_raw.data` の頻度・サイズ
   - `transcript.data` が webhook と WS の両方で来ること
5. 実 envelope を spec 2 章と突合せ、ズレがあれば修正

### 5.2 検収項目

- [ ] WS Upgrade が 101 で確立
- [ ] 認証ヘッダのキー名（`svix-*` か `webhook-*` か）を確定
- [ ] `bot.id` の出現位置を確定
- [ ] base64 デコード後のサンプル数 / レイテンシ概算
- [ ] エラー時の close code をログから把握

### 5.3 Exit Criteria
- 上記検収項目すべて確認、必要なら spec を補強した PR を merge
- WS 経路で受けた `transcript.data` から生成された `Utterance` が Webhook 経路と**同一会議で同一文章を生成**（差分 ≤ 数件）

### 5.4 ロールバック
- env を `webhook` に戻してデプロイ。コードは残置でも害なし

---

## 6. Phase 4 — Dev で WS 単独運用 (`websocket` モード) — 1 週間

### 6.1 切替
- dev env: `RECALL_TRANSPORT=websocket`
- Webhook の Recall ダッシュボード設定はそのままにし、bot 作成時にだけ WS のみ送る形にする（bot 作成 body 側で webhook を出さなくなるので静かに止まる）

### 6.2 監視
- Application Insights の `ContainerAppConsoleLogs`
- 1 日 1 回ログサマリ確認：drop 件数、未知 event、認証失敗、接続継続時間
- Recall 側の **endpoint failure 通知**を Slack/メールで受ける設定

### 6.3 Exit Criteria
- 7 連続日で：drop frame 0、認証失敗 0、未処理例外 0、`transcript.data` 件数が前週の Webhook と同水準
- bot↔meeting 解決失敗 0

### 6.4 ロールバック
- env を `both` か `webhook` に戻して再デプロイ

---

## 7. Phase 5 — Prod へ段階移行 (`both` → `websocket`)

### 7.1 手順

| 日 | 操作 |
|---|---|
| Day 0 | prod env `RECALL_TRANSPORT=both` でデプロイ |
| Day 1-3 | 二重受信を許容（Cosmos の `utterance` は **WS 側のみ**保存して二重保存を避ける、後述 8 章）|
| Day 4 | prod env `RECALL_TRANSPORT=websocket` でデプロイ |
| Day 4-10 | 監視 |

### 7.2 二重受信時の de-dup
- Phase 5 期間は **`RECALL_TRANSPORT=both` でも Cosmos `save_utterance` と `orchestrator.process` は WS 側のみ実行**するため、`main.py` で Webhook 側 `on_utterance` を **dry-run モード**に切り替える env を一つ追加：
  - `RECALL_WEBHOOK_DRY_RUN=true` → ログだけ出し、Cosmos と orchestrator を呼ばない
  - WS 側は通常動作
- これで「両方受けるが orchestrator は 1 回しか呼ばれない」を担保

### 7.3 Exit Criteria
- 7 連続日 prod で：`utterance` 重複なし、エラーレート < 0.1%、レイテンシ指標が WS で前週同等または改善
- Recall.ai 側で endpoint failure が発生していない

### 7.4 ロールバック
- env を `both` + `RECALL_WEBHOOK_DRY_RUN=false` に戻し、Webhook 側に主役を戻して再デプロイ
- これで 5 分以内に旧運用に復帰可能

---

## 8. Phase 6 — クリーンアップ（破壊的変更）

### 8.1 削除対象

| 対象 | 理由 |
|---|---|
| `src/api/recall_router.py` の `RecallWebhookRouter` | 簡易版・署名検証なし・payload パース破綻。spec 12 章で WS が主役に |
| `tests/test_recall_router.py` | 上記とセット |
| `main.py:110` の `RecallWebhookRouter(...).register(app)` | 上記をマウントしている行 |
| `infra/outputs.tf` の `recall_webhook_url` を `recall_ws_url` に置換 / 併記 | ドキュメント整合 |
| `docs/api-server.md` の `POST /api/recall/transcript` 節 | WS 節へ差し替え |

`RecallWebhookHandler` (`recall_source.py`) と `/api/recall/webhook` は **当面残置**（Recall 側設定が webhook のままでも事故らないように）。`RECALL_TRANSPORT=webhook` を fallback として残す。

### 8.2 ガード
- 削除 PR 単体で merge し、prod へは 1 リリース挟んでデプロイ（rollback 容易性のため）

### 8.3 Exit Criteria
- 1 週間 prod で `RECALL_TRANSPORT=websocket` 運用継続
- 削除 PR の CI 全 GREEN

---

## 9. デプロイ・運用チェックリスト

### 9.1 デプロイ前
- [ ] Key Vault に `RECALL_WS_PUBLIC_URL` 登録
- [ ] Container Apps の ingress が WebSocket 通すか確認（`transport: auto` で OK のはずだが要再確認）
- [ ] Recall.ai workspace secret が dev / prod で同一 or 適切に分離されているか
- [ ] `recall_ws_url` の Terraform output が正しい

### 9.2 デプロイ後 (smoke test)
```bash
# Upgrade レイヤだけ確認（署名なしなら 401）
curl -i \
  -H "Connection: Upgrade" \
  -H "Upgrade: websocket" \
  -H "Sec-WebSocket-Version: 13" \
  -H "Sec-WebSocket-Key: dGVzdHRlc3R0ZXN0dGVzdA==" \
  https://<host>/api/recall/ws
# 期待: 401 (auth 不備でも Upgrade 自体は配線済み)
```

### 9.3 観測項目
- `ContainerAppConsoleLogs` で `recall_ws_handler` フィルタ
- KQL 例:
  ```kql
  ContainerAppConsoleLogs
  | where Log contains "recall_ws_handler"
  | summarize count() by tostring(parse_json(Log).level), bin(TimeGenerated, 5m)
  ```

---

## 10. TODO（実装着手順）

実装は Phase 1 のサブタスク 1.1 〜 1.10 を順に進める。テスト (Phase 2) は実装と並行ではなく、各サブタスクの単体テストを書き終えてから次へ。

```
Phase 1
  1.1  Config 追加               ─┐
  1.2  AudioSink Protocol         │ Phase 1 を 1 PR にまとめる
  1.3  RecallWsHandler            │
  1.4  RecallWsRouter             │
  1.5  RecallBotClient 改修       │
  1.6  Cosmos find_meeting_by_*   │
  1.7  transcript_pipeline 抽出   │
  1.8  app.py 配線                │
  1.9  main.py 配線               │
  1.10 Terraform output           │
                                  ┘
Phase 2  全テスト
Phase 3  Dev デプロイ + 観察    ← 実トラフィックで spec 補強
Phase 4  Dev WS 単独運用
Phase 5  Prod ロールアウト
Phase 6  クリーンアップ
```

---

## 11. 受け入れ条件（全体）

- [ ] `RECALL_TRANSPORT=webhook` のままの運用が 100% 後方互換
- [ ] `RECALL_TRANSPORT=websocket` で会議 1 件を完走でき、`utterance` が Webhook 時代と同等数生成される
- [ ] WS 経路で `audio_mixed_raw.data` を **少なくとも 1 件以上**処理し、PCM のバイト数 / 秒が 32 kB/s 近傍であることをログで確認
- [ ] ドキュメント (`docs/api-server.md`) が新 WS エンドポイントの設定手順 / 認証 / トラブルシュートを網羅
