# MOCHI-kiki

**Teams 会議サポートエージェント** — 会議の議論を常時リスニングし、不明点の補完・曖昧発言の明確化を Teams チャットへ即座に投稿する常駐型 AI ボット。

Microsoft Agent Hackathon powered by Tokyo Electron Device 応募作品。

---

## 何ができるか

会議中に Teams 会議へ参加し、以下を自動で行う。

- **会議リスニング**: 全発話をリアルタイムで取得（Recall.ai または Microsoft Graph 経由）
- **仕様補完**: 会話中に出てきた用語・仕様を Azure AI Search の RAG で検索して提示
- **発言明確化**: 曖昧な発言を検知し、発言者への確認 → 調査 → 整理した内容をチャットへ投稿
- **発話ログの永続化**: Cosmos DB に保存

エージェント本体のランタイム LLM は **Azure OpenAI (GPT-4o 系)**。Claude は開発支援に限定使用。

---

## アーキテクチャ概略

```
Teams Meeting
  ├─ Recall.ai bot ──(webhook / WS)──┐
  └─ Graph subscription ─────────────┤
                                     ▼
                          aiohttp (src/main.py)
                                     │
                                     ▼
                    Orchestrator (Semantic Kernel)
                     ├─ Intent / Ambiguity plugins
                     ├─ RAG Search (Azure AI Search)
                     └─ Answer Generation
                                     │
                          ┌──────────┴──────────┐
                          ▼                     ▼
                  Cosmos DB (発話ログ)    Teams Chat (投稿)
```

主要モジュール:

| パス | 役割 |
|------|------|
| `src/main.py` | エントリーポイント。依存配線と aiohttp 起動 |
| `src/bot/` | Bot Framework アダプタ + Teams ハンドラ |
| `src/transcript/` | Recall.ai (webhook / WS) / Graph 発話ソース |
| `src/kernel/` | Semantic Kernel オーケストレータ |
| `src/plugins/` | 意図解析・曖昧検知・回答生成プラグイン |
| `src/services/` | RAG 検索・Teams チャット投稿 |
| `src/storage/` | Cosmos DB クライアント |
| `infra/` | Terraform (Azure Container Apps / Cosmos / Search / KV / OpenAI) |
| `teams_app/` | Teams アプリ manifest と zip パッケージ |
| `scripts/` | デプロイ・診断・E2E テスト用スクリプト |
| `articles/` | Zenn 記事ドラフト |

---

## 必要環境

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (依存解決・実行)
- Azure サブスクリプション (Container Apps / Cosmos DB / OpenAI / AI Search / Key Vault)
- Recall.ai アカウント (発話ソースに `recall` を使う場合)
- Microsoft 365 テナント (Teams アプリ配布用)

---

## セットアップ

```bash
# 依存インストール
uv sync

# 環境変数テンプレートをコピーして埋める
cp .env.example .env

# ローカル起動 (デフォルト :3978)
uv run python -m src.main
```

主要な環境変数は `.env.example` を参照。設定検証は `src/config.py` に集約されており、不正値は起動時に fail-fast する。

発話ソース切替:

| `TRANSCRIPT_SOURCE` | 経路 |
|---|---|
| `graph` | Microsoft Graph subscription |
| `recall` | Recall.ai bot |
| `both` | 両方 |

Recall.ai を使う場合は `RECALL_TRANSPORT` で `webhook` / `websocket` / `both` を選択する。

---

## デプロイ

Azure Container Apps + Terraform を使う。

```bash
# Azure リソース一式 (Cosmos / Search / OpenAI / KV / ACA など)
cd infra
terraform init
terraform apply -var-file=terraform.tfvars

# Container Apps へのコンテナ更新
./scripts/deploy_recall_ws.sh
```

Teams への配布は `teams_app/mochi-kiki.zip` を Teams 管理センターまたはサイドロードで取り込む。詳細は `docs/teams-install.md`。

---

## テスト

```bash
# pytest (asyncio mode auto)
uv run pytest

# Recall.ai WS のローカル疎通確認
./scripts/test_recall_ws.sh

# E2E 雛形
uv run python scripts/local_e2e_test.py
```

---

## ドキュメント

- `要件定義書_Teams会議サポートエージェント.md` — 要件・スケジュール・審査基準マッピング
- `docs/api-server.md` — API エンドポイント仕様
- `docs/recall-quickstart.md` / `docs/recall-teams-manual.md` — Recall.ai セットアップ手順
- `docs/deploy-recall-ws.md` — WS 経由デプロイ手順
- `docs/infra.md` — Terraform 構成
- `docs/teams-install.md` — Teams アプリ配布手順

---

## 開発体制

社内 2 名チームで開発。Claude は開発支援アシスタント (GitHub Copilot と同じ位置付け) として使用し、ランタイム推論には用いない。
