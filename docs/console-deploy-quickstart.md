# 管理コンソール (frontend-bot-console) Deploy クイックスタート

仕様: `docs/superpowers/specs/2026-05-29-frontend-bot-console.md`
最終更新: 2026-05-30

このドキュメントは「ローカルの frontend から、本番 Container App backend を経由して **実際に Teams 会議に bot を投入する**」までの最短手順をまとめたものです。

---

## 全体像

```
ブラウザ → frontend (localhost:3000) → /api/console/* → rewrites
        ↓
   Azure Container App (既存 backend + 今回追加された /api/console/*)
        ↓
   Recall.ai API + Cosmos DB (既存)
```

frontend は静的に動かす dev server。バックエンド処理 (Recall.ai 呼び出し、Cosmos 読み書き、JWT 発行など) は全部 Azure 側に集約します。credentials が frontend に漏れない構成です。

---

## ユーザー実行が必要な作業

> 私 (bg session) の権限では Azure 認証ができないので、ここはユーザー側で実行してください。

### 1. backend を Container App に deploy

```bash
cd <repo-root>

# 1-1. az login (済みなら skip)
az login
az account set --subscription <YOUR_SUBSCRIPTION_ID>

# 1-2. スクリプトの内容を確認
cat scripts/deploy_console.sh

# 1-3. dry-run でコマンドの中身だけ見る (任意)
bash scripts/deploy_console.sh --dry-run

# 1-4. 実 deploy (admin / admin)
bash scripts/deploy_console.sh

# パスワードを変えたい場合
bash scripts/deploy_console.sh --user admin --password 'YOUR_PW'
```

実行終了時に **Container App URL** が表示されます (例: `https://mochikiki-bot-dev.xxxxx.japaneast.azurecontainerapps.io`)。

**スクリプトがやること**:
1. `az containerapp secret set` で `console-password-hash`, `console-jwt-secret` を upsert
2. `az containerapp update --set-env-vars` で `CONSOLE_ENABLED=true` 等を追加 (既存 env はマージで保持)
3. `docker build` + `az acr login` + `docker push` で新 image を作成
4. `az containerapp update --image` で新 revision に切り替え
5. `curl <URL>/api/console/auth/me` で 401 が返ることを確認 (ルート有効化チェック)

### 2. frontend 側の設定

```bash
cd frontend
echo "BACKEND_URL=https://<上で出た FQDN>" > .env.local
npm run dev
```

`BACKEND_URL` が **設定されると**、frontend 内蔵の dev mock は応答せず、`next.config.ts` の rewrites (`beforeFiles`) が backend に向けてプロキシします。

### 3. ブラウザで動作確認

1. http://localhost:3000/ にアクセス → `/login` にリダイレクト
2. **admin / admin** (or `--user/--password` で設定したもの) でログイン
3. `/bots/new` で Teams 会議 URL を入れて投入 → 実 Recall.ai API call → 本物の Teams 会議に bot が参加
4. `/meetings` で進行中・過去の会議が見える (Cosmos から実データ)
5. `/meetings/<id>` で文字起こしが 5 秒ポーリングで増えていく

---

## 環境変数

`TF_PREFIX` / `TF_ENV` / `TF_RG` を上書きすると別環境にデプロイできます (デフォルトは `infra/variables.tf` の default 値):

```bash
TF_PREFIX=mochikiki TF_ENV=prod TF_RG=rg-mochi-kiki-prod \
  bash scripts/deploy_console.sh
```

| 変数 | デフォルト |
|---|---|
| `TF_PREFIX` | `mochikiki` |
| `TF_ENV` | `dev` |
| `TF_RG` | `rg-mochi-kiki` |

---

## トラブルシュート

### `Container App '...' が見つかりません`
`TF_PREFIX` / `TF_ENV` / `TF_RG` が環境に合っていない。`infra/terraform.tfvars` の値と揃えてください。

### `python3 に bcrypt がありません`
ローカル python に bcrypt をインストール:
```bash
pip install bcrypt
```

### deploy 後も `/api/console/*` が 404
- Container App の revision が新 image に切り替わっていない可能性。
- `az containerapp revision list -n mochikiki-bot-dev -g rg-mochi-kiki -o table` で `Active=True` の revision を確認。
- `az containerapp logs show -n mochikiki-bot-dev -g rg-mochi-kiki --tail 50` で起動エラーを確認。
- `CONSOLE_ENABLED` が `true` でないと console_router は register されない。

### ログインしても 401 ループ
- Cookie が保存されていない可能性。Container App の URL は HTTPS なので `CONSOLE_COOKIE_SECURE=true` で OK のはず。
- ブラウザの devtools で Set-Cookie ヘッダを確認 (`mochi_session=...; Secure; HttpOnly; SameSite=Strict`)。

### Bot 投入で 502 `recall_api_error` が返る

Container App ログに `POST https://<region>.recall.ai/api/v1/bot/ failed status=401` が出ているなら、Container App の `RECALL_REGION` と Recall.ai dashboard で発行した API key の region が一致していない可能性が高いです (key は region 別)。

```bash
# 1. .env と Container App env を比較
grep '^RECALL_REGION=' .env
az containerapp show -n mochikiki-bot-dev -g rg-mochi-kiki \
  --query "properties.template.containers[0].env[?name=='RECALL_REGION'].value" -o tsv

# 2. ズレていたら Container App 側を .env に合わせる (例: us-west-2)
az containerapp update -n mochikiki-bot-dev -g rg-mochi-kiki \
  --set-env-vars "RECALL_REGION=us-west-2"
```

`status=400` なら meeting_url が Recall.ai 側で不正と判定 (Teams 会議が既に終了している / URL 形式違反 / dummy URL 等)。本物の Teams 会議 URL を使ってください。

### Cosmos の meetings が空
- 過去の bot 投入 (例: `scripts/test_recall_ws.sh` 経由) の record はそのまま見えるはず。
- 新規 console 経由の投入は `id=console-<unix_ts>-<rand4>` 形式。
- Cosmos Explorer で `meetings` コンテナを確認。

---

## 削除手順

CONSOLE_* を完全に外したいとき:

```bash
# env 削除
az containerapp update \
  --name mochikiki-bot-dev --resource-group rg-mochi-kiki \
  --remove-env-vars CONSOLE_ENABLED CONSOLE_USERNAME CONSOLE_PASSWORD_HASH \
                    CONSOLE_JWT_SECRET CONSOLE_COOKIE_SECURE

# secret 削除
az containerapp secret remove \
  --name mochikiki-bot-dev --resource-group rg-mochi-kiki \
  --secret-names console-password-hash console-jwt-secret
```

`CONSOLE_ENABLED=false` (または未設定) になると `src/main.py` は console_router を register しないので、`/api/console/*` は 404 に戻ります。フロントは dev mock にフォールバックします (BACKEND_URL を `.env.local` から消せば mock 動作)。
