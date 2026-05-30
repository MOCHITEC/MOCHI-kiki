# MOCHI-kiki 管理コンソール (frontend)

仕様: `docs/superpowers/specs/2026-05-29-frontend-bot-console.md`

Next.js (App Router) で実装した、Teams 会議に Recall.ai bot を投入する管理画面です。

## 画面

| Path | 用途 |
|---|---|
| `/login` | ログイン |
| `/bots/new` | Bot 投入フォーム |
| `/meetings` | 会議 (= bot) 一覧 |
| `/meetings/:meetingId` | 会議詳細 / 文字起こし (5 秒ポーリング) |

未認証で `/login` 以外を開くと `/login` にリダイレクトします (`src/proxy.ts`)。

## バックエンド連携 / dev mock

`/api/console/*` には 2 つのバックエンドモードがあります。

| `BACKEND_URL` | 挙動 |
|---|---|
| **未設定** (default) | frontend 内の **dev mock** (`src/app/api/console/*`) が応答。`admin` / `admin` でログイン可。in-memory なので再起動で消える |
| 設定済み | `next.config.ts` の `rewrites` (beforeFiles) でその URL にプロキシ。実バックエンド (`src/main.py` の aiohttp) と組み合わせて使う |

```bash
cp .env.example .env.local            # mock のままなら何も書かなくて OK
# 実バックエンドを使うとき:
# echo "BACKEND_URL=http://localhost:3978" >> .env.local
```

Cookie は `credentials: "include"` で同送します。dev mock は `mochi_session=devmock.<base64>` 形式 (Cookie 確認用)、本物の backend は HS256 JWT を発行します。

## 開発

```bash
npm install
npm run dev          # http://localhost:3000
```

別途、バックエンド (`src/main.py` の aiohttp サーバ) を `http://localhost:8000` で起動してください。
バックエンド側の `/api/console/*` ルート (auth / bots / meetings) は仕様書 4 章を参照。

## ビルド

```bash
npm run build
npm start
```

## 構成

- Next.js 16 (App Router) + TypeScript + Tailwind CSS v4
- `@tanstack/react-query` — API キャッシュ / 5 秒ポーリング
- `react-hook-form` + `zod` — フォーム validation
- `sonner` — トースト
- 認証ガードは `src/proxy.ts` (Next.js 16 で `middleware.ts` から改名)

```
src/
├── app/
│   ├── (authed)/             認証必須グループ
│   │   ├── layout.tsx        ヘッダ付きレイアウト
│   │   ├── bots/new/
│   │   └── meetings/
│   │       ├── page.tsx      一覧
│   │       └── [meetingId]/
│   ├── login/page.tsx
│   ├── layout.tsx            QueryProvider + Toaster
│   └── page.tsx              /meetings へ redirect
├── components/
│   ├── Nav.tsx
│   ├── QueryProvider.tsx
│   └── ui/                   shadcn 風の最小コンポーネント
├── lib/
│   ├── api.ts                fetch ラッパ
│   ├── types.ts
│   └── utils.ts
└── proxy.ts                  認証ガード (mochi_session cookie)
```
