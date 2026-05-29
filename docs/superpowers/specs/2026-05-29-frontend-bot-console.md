# MOCHI-kiki 管理コンソール (フロントエンド) 仕様書

作成日: 2026-05-29
ステータス: Draft (MVP scope)

---

## 1. 目的

現状 `./scripts/test_recall_ws.sh` を手で叩いて Recall.ai bot を Teams 会議に投入している運用を、
ブラウザから誰でも操作できる **管理コンソール (Web UI)** に置き換える。
あわせて、運用上 最低限ほしい補助機能 (bot 一覧 / 文字起こし閲覧) も同じ UI に同居させる。

非目標 (Out of scope):
- ロール / 権限管理
- マルチテナント
- リアルタイムストリーミング表示 (文字起こしは保存後の閲覧のみ)
- Bot Framework 経由 (Teams からの自動投入) の置換 — これは現行どおり残す

---

## 2. ユーザーストーリー (MVP)

| # | As a | I want to | So that |
|---|---|---|---|
| US-1 | 運営担当 | ID / パスワードでログインする | 社外に公開せず限定運用できる |
| US-2 | 運営担当 | Teams 会議 URL を入力して bot を投入する | シェルを開かずに会議に MOCHI-kiki を呼べる |
| US-3 | 運営担当 | 投入済みの bot 一覧を見る | いま動いているもの / 過去のものを把握できる |
| US-4 | 運営担当 | 指定した bot を会議から退出させる | 終わった bot を手動で leave_call できる |
| US-5 | 運営担当 | 会議の文字起こしをブラウザで読む | `show_transcript.py` を叩かずに済む |

---

## 3. 画面構成 (5 画面)

```
/login                 ログイン
/                      ダッシュボード (= /meetings にリダイレクト)
/bots/new              Bot 投入フォーム            (US-2)
/meetings              会議 (= bot) 一覧            (US-3, US-4)
/meetings/:meetingId   会議詳細 / 文字起こし表示   (US-5)
```

### 3.1 `/login`
- フィールド: `username`, `password`
- 成功: HttpOnly Cookie に session token を発行 → `/meetings` へ
- 失敗: 401 表示

### 3.2 `/bots/new`
- フィールド:
  - `meeting_url` (必須, `https://teams.(microsoft|live).com/` で始まる validation)
  - `bot_name` (任意, default = `MOCHI-kiki`)
  - `language_code` (default = `ja`, select: `ja` / `en`)
- ボタン: **「会議に投入」**
- 投入後: `bot_id` と `meeting_id` をトーストで表示 → `/meetings/:meetingId` へ遷移
- 内部処理: 既存 `scripts/test_recall_ws.sh` と同等
  1. Recall API `POST /api/v1/bot` に WS endpoint 付きで投入
  2. レスポンス `id` を `recall_bot_id` として Cosmos `meetings` コンテナに upsert

### 3.3 `/meetings`
- カラム: `meeting_id` / `bot_name` / `recall_bot_id` / `started_at` / `ended_at` / `utterance 数` / アクション
- 並び順: `started_at DESC`
- ページング: 初期 50 件、Load more 形式 (cursor = `started_at`)
- アクション列:
  - `[退出させる]` — `ended_at` が null のときのみ表示。押すと Recall `POST /api/v1/bot/{bot_id}/leave_call/`
  - `[詳細]` — `/meetings/:meetingId` へ

### 3.4 `/meetings/:meetingId`
- ヘッダ: meeting_id / recall_bot_id / started_at / ended_at / utterance 数 / `[Plain text DL]`
- 本文: `utterances` を `timestamp ASC` で並べた発話ログ
  ```
  [2026-05-29T10:01:22Z] 田中 太郎:
    この仕様は正しいですか
  ```
- 自動更新: 5 秒ポーリング (会議中の進捗を見れる)

---

## 4. バックエンド API 仕様 (新規)

既存の `src/main.py` に同居する aiohttp サーバに、以下のルートを追加する。
すべて `/api/console/*` プレフィックスで分離する。
レスポンスは JSON, 文字コードは UTF-8 固定。

### 4.1 認証

| Method | Path | 用途 |
|---|---|---|
| POST | `/api/console/auth/login` | `{username, password}` → Set-Cookie: `mochi_session=<jwt>; HttpOnly; Secure; SameSite=Strict`。`exp = 12h` |
| POST | `/api/console/auth/logout` | Cookie 削除 |
| GET  | `/api/console/auth/me` | 現在のセッション確認。401 でログイン画面に飛ばす |

- 認証情報は env で 1 組だけ持つ (MVP):
  - `CONSOLE_USERNAME`
  - `CONSOLE_PASSWORD_HASH` (bcrypt, `pip install bcrypt`)
  - `CONSOLE_JWT_SECRET` (HS256)
- 以降の `/api/console/*` (auth/* を除く) は cookie 必須。なければ 401。

### 4.2 Bot 投入 / 操作

| Method | Path | Body | 動作 |
|---|---|---|---|
| POST | `/api/console/bots` | `{meeting_url, bot_name?, language_code?}` | 既存 `RecallBotClient.create_bot` を呼ぶ → Cosmos `meetings` に upsert → `{meeting_id, bot_id}` を 201 で返す |
| POST | `/api/console/bots/:bot_id/leave` | none | Recall `POST /api/v1/bot/{bot_id}/leave_call/` → 成功時 Cosmos `meetings.ended_at = now()` をセット → 202 |

- `meeting_id` は `scripts/test_recall_ws.sh` の挙動に合わせて `console-<unix_ts>-<rand4>` 形式で発番。
- 既存 `MeetingBot.on_teams_meeting_start_activity` 経由の投入と衝突しない。
- WS endpoint URL は `RECALL_WS_PUBLIC_URL` env から取得 (既存 `Config` を再利用)。

### 4.3 会議一覧 / 詳細

| Method | Path | Query | 動作 |
|---|---|---|---|
| GET | `/api/console/meetings` | `limit=50&before=<iso8601>` | Cosmos `meetings` を `started_at DESC` で取得。`utterance_count` は `utterances` を `COUNT` (MVP は近似値で OK) |
| GET | `/api/console/meetings/:meeting_id` | none | meeting メタ + 発話件数を返す |
| GET | `/api/console/meetings/:meeting_id/utterances` | `since=<iso8601>&limit=500` | `utterances` を `timestamp ASC` で返す。ポーリング差分取得対応 |
| GET | `/api/console/meetings/:meeting_id/transcript.txt` | none | plain text ダウンロード (`show_transcript.py --plain` 相当) |

### 4.4 エラーレスポンス共通

```json
{ "error": { "code": "string", "message": "string" } }
```

| HTTP | code | 例 |
|---|---|---|
| 400 | `invalid_meeting_url` | Teams URL の形式違反 |
| 401 | `unauthorized` | Cookie なし / 期限切れ |
| 404 | `meeting_not_found` | 不正な meeting_id |
| 502 | `recall_api_error` | Recall API の non-2xx を素通しせず包む |

---

## 5. フロントエンド構成

| 項目 | 採用 | 理由 |
|---|---|---|
| Framework | **Next.js 15 (App Router) + TypeScript** | Vercel/Static export いずれも対応。SPA 化も簡単 |
| UI | **Tailwind CSS + shadcn/ui** | 既製コンポーネントで MVP 工数を抑える |
| 状態管理 | React Query (`@tanstack/react-query`) | API キャッシュ + ポーリングが楽 |
| Form | react-hook-form + zod | 入力 validation |
| 配置 | リポジトリ内 `frontend/` ディレクトリ | モノレポ的に同居 |

ビルド成果物は静的ファイルにし、aiohttp サーバの `app.router.add_static("/")` で配信する。
(別 Container App を立てる選択肢もあるが、MVP は同居で十分)

---

## 6. データモデル (Cosmos)

### `meetings` (既存, 追加カラムあり)
```jsonc
{
  "id": "console-1717012345-ab12",         // meeting_id
  "thread_id": "console",                  // フロントエンド経由は固定値
  "organizer_id": "<console username>",    // ログインユーザ名
  "started_at": "2026-05-29T10:00:00Z",
  "ended_at": null,                        // leave_call 後にセット
  "recall_bot_id": "bot_xxx",
  "transcript_source": "recall",
  "meeting_url": "https://teams.live.com/...",   // ★ 表示用に追加
  "bot_name": "MOCHI-kiki"                       // ★ 表示用に追加
}
```

- 既存スキーマと衝突しないよう `meeting_url` / `bot_name` は新規追加。
- 既存 `started_at`/`ended_at`/`recall_bot_id` は流用。

### `utterances` (既存, 変更なし)
`show_transcript.py` の参照スキーマをそのまま使う。

---

## 7. セキュリティ要件 (MVP)

- HTTPS 必須 (Azure Container Apps の ingress で TLS 終端済み)
- Cookie: `Secure; HttpOnly; SameSite=Strict`
- JWT secret は Key Vault → env 注入 (`infra/main.tf` に追加)
- パスワードは bcrypt cost=12 で保存。env には **ハッシュ済の値のみ** 入れる
- ブルートフォース対策: ログイン失敗を IP 単位で 1 分 10 回まで (in-memory bucket で MVP OK)
- CSRF: SameSite=Strict + JSON body のみで API 受付 → MVP は対策必要なし
- ログイン画面以外の `/api/console/*` 全部に認証ミドルウェアを噛ませる

---

## 8. 環境変数 (新規)

| 変数 | 例 | 役割 |
|---|---|---|
| `CONSOLE_USERNAME` | `admin` | ログイン ID |
| `CONSOLE_PASSWORD_HASH` | `$2b$12$...` | bcrypt ハッシュ |
| `CONSOLE_JWT_SECRET` | 64bytes ランダム | セッション署名 |
| `CONSOLE_ENABLED` | `true` | 安全弁。false なら `/api/console/*` を 404 |

`infra/` の Terraform 側でも Key Vault シークレットを追加する (`tfvars` 編集 + `terraform apply`)。

---

## 9. テスト計画

| レイヤ | テスト |
|---|---|
| API unit | `tests/api/test_console_router.py` — login / bot 投入 / leave / utterances を mocked Recall + in-memory Cosmos で検証 |
| API e2e | 既存 `local_e2e_test.py` パターンに合わせて `local_e2e_console.py` を追加 |
| Frontend unit | React Testing Library で form / list の renderer をテスト |
| Frontend e2e | Playwright で login → 投入 → 一覧表示までの happy path のみ |

---

## 10. 実装フェーズ (推奨順序)

1. **Phase A — Backend**: `/api/console/*` ルートを aiohttp に追加 (auth, bots, meetings)
2. **Phase B — Auth infra**: env / Key Vault / Terraform を更新
3. **Phase C — Frontend skeleton**: Next.js セットアップ + ログイン + bot 投入 1 画面
4. **Phase D — Frontend list/detail**: meetings 一覧 + 詳細 + leave ボタン
5. **Phase E — Deploy**: 静的ビルドを container に同梱、本番動作確認

各フェーズが小さく PR にできるサイズになるよう設計してある。

---

## 11. 既存資産との対応

| 既存 | 置換後 |
|---|---|
| `scripts/test_recall_ws.sh` | `/api/console/bots` POST + `/bots/new` UI |
| `scripts/show_transcript.py` (一覧) | `/meetings` UI |
| `scripts/show_transcript.py <meeting_id>` | `/meetings/:meetingId` UI |
| `curl POST .../leave_call/` | `/api/console/bots/:bot_id/leave` |

シェルスクリプトは残しておき、緊急時の手動オペレーションに使えるようにする。

---

## 12. オープンな決め事

以下は実装着手前に決める必要があるが、デフォルト案を提示しておく:

- ログインユーザは複数必要か? → MVP は **1 ユーザ固定**。将来 Cosmos `users` コンテナに移行
- 監査ログは要るか? → MVP は **不要**。Container Apps の console log で十分
- Bot 投入の確認ダイアログは出すか? → **出す** (誤投入防止)。`test_recall_ws.sh` の Enter プロンプトと同等
- 文字起こしの自動更新間隔 → **5 秒**。長い会議でも Cosmos RU は十分余裕
