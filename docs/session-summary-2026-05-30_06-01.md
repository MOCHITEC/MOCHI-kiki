# MOCHI-kiki セッションまとめ (2026-05-30 〜 2026-06-01)

3 日間で MOCHI-kiki に「管理コンソール」「Recall.ai 連携」「ライブ議事録」を追加し、コスト削減と認証情報の整備まで完了させた記録。

---

## Day 1 (2026-05-30): 管理コンソール構築 + Recall 連携

### 実装したもの

| 項目 | 内容 |
|---|---|
| 仕様書策定 | `docs/superpowers/specs/2026-05-29-frontend-bot-console.md` (Phase A〜E) |
| Phase A (Backend) | `src/api/console_router.py` に `/api/console/*` 8 エンドポイント追加 (JWT + bcrypt + IP rate limit) |
| Phase A (依存) | `pyproject.toml` に `bcrypt`, `PyJWT` 追加 |
| Phase A (Config) | `CONSOLE_USERNAME` / `CONSOLE_PASSWORD_HASH` / `CONSOLE_JWT_SECRET` env を追加 |
| Phase A (Cosmos) | `list_meetings_for_console`, `get_meeting_for_console`, `list_utterances_for_meeting` 等 |
| Phase C/D (Frontend) | Next.js 16 + Tailwind v4 で 5 画面 (`/login`, `/bots/new`, `/meetings`, `/meeting?id=...`) |
| Frontend 認証ガード | Next.js 16 で `middleware.ts` → `proxy.ts` に改名 |
| Phase E (Deploy) | `scripts/deploy_console.sh`、`docs/console-deploy-quickstart.md` |
| Frontend 同梱配信 | Dockerfile を multi-stage 化、`src/api/static_router.py` で Next.js export を aiohttp が配信 |

### 発覚した不具合と修正

| 問題 | 原因 | 修正 |
|---|---|---|
| azure-cosmos 4.16 で `/meetings` 一覧が 500 | `enable_cross_partition_query=True` kwarg が新版で削除 | cosmos クエリから削除 |
| revision rollout が `no child with platform linux/amd64` で失敗 | Mac arm64 で build した manifest が arm64 のみ | `docker buildx build --platform linux/amd64 --push` に変更 |
| Bot Framework messaging endpoint が `--0000001` の古い revision URL | 過去設定が固定化されていた | 安定 URL (revision suffix 無し) に更新 |
| Recall.ai webhook/WS URL も同じ問題 | 同上 | secret と env を安定 URL に upsert |

### 主要な気づき

- 既存 `find_meeting_id_by_recall_bot_id` にも同じ kwarg バグがあり、Recall WS で取得した transcript が `bot_id` を `meeting_id` としてフォールバック保存されていた
- 過去の test 系 53 件 + 当日 1 件、計 54 件の utterance が「迷子 partition」に保存されていた
- migration で全 54 件を正しい `meeting_id` partition に移行

### 認証情報 (Day 1 時点)

```
ID: admin
PW: admin
URL: https://mochikiki-bot-dev.orangeglacier-d7a5339f.japaneast.azurecontainerapps.io/login/
```

---

## Day 2 (2026-05-31): Teams App 試行 → Recall.ai 経路への乗り換え

### Teams App パッケージ作成 (途中で方針転換)

- `teams-app/manifest.json` 作成、`mochi-kiki.zip` 生成
- 組織カタログに upload 成功 (バージョン 1.0.2)
- `webApplicationInfo` と RSC permission (`OnlineMeeting.ReadBasic.Chat` 等) を追加
- `configurableTabs` を追加 (Tab Web ページも実装、`/tab/configure`、`/tab/content`)

### しかし会議でアプリ追加 UI が動かず

- 会議の編集画面に「+」タブ追加ボタンが見当たらない問題
- 公式 docs 探索の結果、Python 公式サンプルが存在しないことが判明
  - `meetings-events` サンプル: C# / Node.js のみ (Python なし)
  - `graph-proactive-installation`: 同上
  - `Proactive Messaging`: 同上
- ハマりまくった末、ユーザーから「Recall.ai bot は手動投入できるのでは?」のヒント

### Recall.ai 公式 docs を読み直して大発見

Recall.ai 公式に **明記**:
> "Microsoft Teams: Yes, supported ✅" (Sending Chat Messages)

つまり Recall.ai bot が **Teams 会議のチャットに直接投稿可能** だった。Teams App install ルートは **全部不要** だった。

### 方針転換: Recall.ai send_chat_message ルートに切替

- `src/transcript/recall_client.py` に `send_chat_message(bot_id, message)` メソッド追加
- `src/plugins/recall_chat_poster.py` 新規 (meeting_id → bot_id を Cosmos で逆引きして送信)
- `orchestrator._handle_spec_inquiry` と `_handle_ambiguous` を Recall poster 経由に切替
- Bot Framework adapter 経由は fallback として残置

### 動作確認

- 「テストメッセージです」が会議のチャットに **HTTP 200** で着弾
- ユーザーが「テストメッセージ届いてました!」と確認

### 文字起こしの表記揺れ問題

- Recall.ai の `prioritize_accuracy` モード (日本語必須) は **公式で 3-10 分遅延**
- 「もちろん (MOCHIRON)」「持ちきっき (MOCHI-kiki)」のように仮名化される
- 対策として RAG ドキュメントに alias を追加 (`mochiron-alias-001` 等)
- 検索スコア: 「もちろん 代表」が 0.017 → 9.07 に大幅改善

### Day 2 終わりの状態

- ✓ 会議でチャット応答が動く構成完成
- ✓ Cosmos に 54 件の utterance、9 件の MOCHI-kiki 自己仕様
- ✗ ID/Pass はまだ admin/admin

---

## Day 3 (2026-06-01): ライブ議事録機能 + コスト削減 + 認証変更

### ライブ議事録機能 (本日のメイン)

実装範囲:

| コンポーネント | ファイル |
|---|---|
| 議事録生成プラグイン | `src/plugins/minutes_generator.py` (GPT-4o で「議題/決定/TODO/質疑応答」Markdown 整形) |
| タイムライン要約プラグイン | `src/plugins/timeline_summarizer.py` (5 分単位、各ブロックを 150 字以内に要約) |
| Cosmos 拡張 | `upsert_minutes`, `upsert_timeline_block` (meetings コンテナのフィールド更新で実装) |
| Orchestrator hook | `_maybe_update_live_minutes` を `process(utterance)` 冒頭で非同期発火、90 秒間隔 |
| 外部 trigger | `refresh_minutes(meeting_id, force=True)` で cooldown 無視 |
| API endpoint | `GET /api/console/meetings/:id/minutes` と `/timeline` |
| Frontend タブ UI | `/meeting?id=...` に「議事録 / タイムライン / 文字起こし」タブ |
| 議事録: 30 秒ポーリング |  |
| タイムライン: 30 秒ポーリング |  |
| 文字起こし: 5 秒ポーリング (既存) |  |

### テスト用 simulate_meeting エンドポイント

```
POST /api/console/test/simulate_meeting
body: { meeting_id, bot_name, delay_seconds, utterances: [{speaker, text}, ...] }
```

Teams 会議に bot を入れずに、ダミー発話を流して議事録生成パイプラインを動作確認できる。

### 動作確認 (test-minutes-002)

10 件の業務会議シミュレーション → 5 件の追加発話 で更新を実証:

| | 10 件時点 | +5 件後 |
|---|---|---|
| utterance | 10 | 15 |
| markdown 長さ | 681 字 | 826 字 |
| 議題数 | 3 | 4 |
| 決定事項 | 月曜 10 時リリース | **水曜 10 時に上書き** + AI Search 削減追加 |
| 質疑応答 | 2 つ | 3 つ |
| タイムラインブロック | 1 | 2 (末尾に新規追加) |

GPT-4o が既存決定 (月曜) を新発話 (水曜に変更) で正しく上書きしたのが特に重要。

### 発覚した問題と修正

| 問題 | 修正 |
|---|---|
| GPT-4o が入力に居ない「鈴木さん」を捏造 | prompt 冒頭に「発話に登場しない人物・組織・数値・期限を絶対に追加しない」を最優先ルール化 |
| ``` ```markdown ... ``` ``` でラップされて返ってくる | prompt で「素の Markdown のみ」を明示 + plugin 側でも先頭/末尾の ``` を除去 |
| utterance_count=1 で議事録更新が止まる (90 秒 cooldown) | `refresh_minutes(force=True)` を simulate_meeting の最後で呼ぶ |
| AmbiguityDetector ルートで応答が来ない | Recall poster 経由に切替 (Bot Framework は fallback) |

### Azure AI Search を Basic → Free に切替

| | Basic | Free |
|---|---|---|
| 月額 | $75 | $0 |
| Index 数上限 | 制限なし (実質) | 3 |
| Documents 上限 | 制限なし | 10,000 |
| Storage 上限 | 15 GB | 50 MB |
| 現状利用 | 1 index, 20 docs, 0.68 MB | 余裕 |

実装:
- 新 service `mochikiki-search-free` 作成 (Japan East)
- `setup_search_index.py` で index 再構築 + 11 件投入
- `upload_mochi_kiki_spec.py` で MOCHI-kiki 仕様 9 件追加 (合計 20 件)
- Container App secret `search-key` 上書き + env `AZURE_SEARCH_ENDPOINT` 更新
- 月 **約 74 ドル削減** (年 1,000 円以上 × 12 ≒ 11,000 円/月)

旧 `mochikiki-search-dev` (Basic) は会議で RAG 動作確認後に削除予定。

### 認証情報変更

| | Before | After |
|---|---|---|
| ID | admin | **mochitec** |
| PW | admin | **Mochitec2026!** |

実装: bcrypt cost=12 でハッシュ生成 → Container App secret `console-password-hash` 上書き + env `CONSOLE_USERNAME` 更新 + revision restart。`.env.example` も合わせて更新済。

---

## 現在の状態

### 動作中の機能

- ✓ 管理コンソール (mochitec / Mochitec2026!)
- ✓ Bot 投入 (UI / スクリプト両対応)
- ✓ 会議一覧 / 詳細 / 文字起こし表示
- ✓ Recall.ai 経由の AI 応答 (会議チャットに [仕様補完] 投稿)
- ✓ ライブ議事録 (議題/決定/TODO/質疑応答、90 秒間隔更新)
- ✓ タイムライン (5 分ブロック、新ブロックのみ追加)
- ✓ RAG 検索 (20 ドキュメント、MOCHIRON + MOCHI-kiki 仕様 + alias)

### コスト概算

- Idle 状態の月額: 約 $50 (AI Search Free 化前は $120 強)
- bot 使用時の追加: Recall.ai $0.05/分 + GPT-4o トークン課金

### 次の検討候補 (未着手)

- 旧 AI Search (Basic) の削除 (会議で動作確認後)
- Container Apps min 1 → 0 (scale-to-zero、cold start リスクあり)
- Cosmos autoscale → Serverless (移行作業大)
- リアルタイム文字起こし高速化 (Deepgram BYOK or Azure Speech 自前 sink)
- 議事録 UI 改善 (react-markdown レンダリング、TODO チェックボックス化、編集機能、PDF/Word ダウンロード)

### URL / ID

```
管理コンソール: https://mochikiki-bot-dev.orangeglacier-d7a5339f.japaneast.azurecontainerapps.io/login/
ID:             mochitec
PW:             Mochitec2026!

PR:             https://github.com/MOCHITEC/MOCHI-kiki/pull/1
```

---

## 試したい場合の手順

### 実会議で試す
1. Teams カレンダーで新規スケジュール会議作成
2. 会議の URL をコピー
3. 管理コンソール `/bots/new` から bot 投入 (もしくは `./scripts/test_recall_ws.sh "<URL>"`)
4. 会議で発話
5. 約 5〜10 分後に会議チャットに `[仕様補完]` 応答が出る
6. 並行して `/meeting?id=<id>` で 議事録 / タイムライン タブが見える

### ダミーで動作確認
```bash
curl -X POST <URL>/api/console/test/simulate_meeting \
  -H "Content-Type: application/json" \
  -d '{"meeting_id":"test","bot_name":"MOCHI-kiki","delay_seconds":0.5,
       "utterances":[{"speaker":"...","text":"..."}, ...]}'
```

---

*このまとめは Claude Code セッションログから整理したものです。技術詳細やコミットメッセージは PR を参照してください。*
