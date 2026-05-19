# MOCHI-kiki インフラストラクチャ設計書

## 概要

MOCHI-kiki は Microsoft Teams 会議の発話をリアルタイムに処理し、仕様確認・曖昧発言の補完を行う AI Botシステムです。すべてのインフラは Terraform（AzureRM プロバイダ v3）で管理し、Azure Japan East リージョンに展開されます。

- **リソースグループ**: `rg-mochi-kiki`
- **リージョン**: `japaneast`
- **環境**: `dev` / `prod`（変数で切り替え）
- **Terraform State 保存先**: Azure Blob Storage（`rg-tfstate` / `mochikiikitfstate`）

---

## Azureサービス一覧

| サービス | リソース名（プレフィックス） | 用途 |
|---|---|---|
| Azure Container Registry | `mochikiki-acr-dev` | Botの Dockerイメージ保管 |
| Azure Container Apps Environment | `mochikiki-cae-dev` | Container Apps の実行環境 |
| Azure Container Apps | `mochikiki-bot-dev` | Bot アプリケーション本体 |
| Azure OpenAI | `mochikiki-oai-dev` | GPT-4o / text-embedding-3-small |
| Azure AI Speech | `mochikiki-speech-dev` | 会議音声のリアルタイム文字起こし |
| Azure AI Search | `mochikiki-search-dev` | 仕様書・社内文書のベクトル検索（RAG） |
| Azure Cosmos DB | `mochikiki-cosmos-dev` | 発話ログ・会議情報・セッション管理 |
| Azure Key Vault | `mochikiki-kv-dev` | APIキー・シークレットの一元管理 |
| Azure User Assigned Identity | `mochikiki-id-bot-dev` | Container Apps の認証ID（Managed Identity） |
| Azure Log Analytics Workspace | `mochikiki-law-dev` | Container Apps のログ集約・監視 |

---

## Azure AI モデル構成

| デプロイ名 | モデル | バージョン | 用途 |
|---|---|---|---|
| `gpt-4o` | GPT-4o | 2024-11-20 | 意図解析・回答生成・曖昧検出 |
| `text-embedding-3-small` | text-embedding-3-small | 1 | ドキュメントのベクトル化（RAG） |

---

## Cosmos DB データベース構成

データベース名: `meeting_db`

| コレクション名 | パーティションキー | 用途 |
|---|---|---|
| `utterances` | `/meeting_id` | 会議ごとの発話履歴 |
| `meetings` | `/id` | 会議メタデータ（参加者・開始/終了時刻） |
| `clarification_sessions` | `/meeting_id` | C-03 曖昧発言の確認セッション |
| `consents` | `/meeting_id` | 録音同意情報 |
| `agent_logs` | `/meeting_id` | AIエージェントの処理ログ |

---

## セキュリティ設計

### Managed Identity

Container Apps は User Assigned Managed Identity（`mochikiki-id-bot-dev`）を使って各Azureサービスに接続します。アプリ内にクレデンシャルを直接持たない設計です。

| 権限 | 対象リソース | ロール |
|---|---|---|
| イメージ取得 | Azure Container Registry | `AcrPull` |
| シークレット読み取り | Azure Key Vault | アクセスポリシー（`Get`, `List`） |

### Key Vault シークレット一覧

| シークレット名 | 内容 |
|---|---|
| `azure-openai-endpoint` | Azure OpenAI エンドポイント URL |
| `azure-openai-key` | Azure OpenAI APIキー |
| `azure-speech-key` | Azure AI Speech APIキー |
| `azure-speech-region` | Azure AI Speech リージョン |
| `azure-search-endpoint` | Azure AI Search エンドポイント URL |
| `azure-search-key` | Azure AI Search APIキー |
| `azure-cosmos-endpoint` | Cosmos DB エンドポイント URL |
| `azure-cosmos-key` | Cosmos DB プライマリキー |
| `acr-login-server` | Container Registry ログインサーバー名 |

---

## Container Apps 設定

| 項目 | 値 |
|---|---|
| CPU | 0.5 vCPU |
| メモリ | 1 GiB |
| ポート | 3978（Bot Framework Messaging Endpoint） |
| 最小レプリカ | 1 |
| 最大レプリカ | 3 |
| リビジョンモード | Single |
| 外部公開 | 有効（HTTPS） |

---

## サービス間の関係図（ワークフロー）

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        Microsoft Teams                                  │
│                                                                         │
│  参加者A ──音声──┐    ┌── Botメッセージ受信（C-03返信）                 │
│  参加者B ──音声──┤    │                                                 │
│  参加者C ──音声──┘    │                                                 │
└───────────────────────│─────────────────────────────────────────────────┘
                        │                           ▲
            音声ストリーム│                           │Bot からチャット投稿
                        ▼                           │
┌───────────────────────────────────────────────────────────────────────────┐
│                  Azure Container Apps（Bot アプリ）                       │
│                                                                           │
│  ┌─────────────────┐    ┌──────────────────────────────────────────────┐ │
│  │  C-01           │    │  Orchestrator（src/kernel/orchestrator.py）  │ │
│  │  音声文字起こし  │───▶│                                              │ │
│  │  (Speech SDK)   │    │  ┌────────────────┐  ┌──────────────────┐   │ │
│  └─────────────────┘    │  │ C-02 パイプライン│  │ C-03 パイプライン│   │ │
│                         │  │                │  │                  │   │ │
│                         │  │ 意図解析       │  │ 曖昧発言検出     │   │ │
│                         │  │    ↓           │  │    ↓             │   │ │
│                         │  │ RAG 検索       │  │ 確認質問生成     │   │ │
│                         │  │    ↓           │  │    ↓             │   │ │
│                         │  │ 回答生成       │  │ 整理文生成       │   │ │
│                         │  └────────────────┘  └──────────────────┘   │ │
│                         └──────────────────────────────────────────────┘ │
│                                                                           │
│  Managed Identity（mochikiki-id-bot-dev）でAzureサービスに認証            │
└───────┬───────────────────────────┬────────────────────┬─────────────────┘
        │                           │                    │
        ▼                           ▼                    ▼
┌───────────────┐   ┌───────────────────────────┐   ┌───────────────────┐
│ Azure AI      │   │    Azure OpenAI            │   │  Azure Cosmos DB  │
│ Speech        │   │                            │   │                   │
│               │   │ ┌─────────────────────┐   │   │  meeting_db       │
│ 会議音声を    │   │ │ gpt-4o              │   │   │  ├─ utterances     │
│ リアルタイムに│   │ │ ・意図分類（C-02）  │   │   │  ├─ meetings       │
│ テキスト変換  │   │ │ ・回答生成（C-02）  │   │   │  ├─ clarification_ │
│               │   │ │ ・曖昧検出（C-03）  │   │   │  │   sessions      │
└───────────────┘   │ │ ・確認質問生成      │   │   │  ├─ consents       │
                    │ └─────────────────────┘   │   │  └─ agent_logs     │
                    │                            │   └───────────────────┘
                    │ ┌─────────────────────┐   │
                    │ │text-embedding-3-    │   │
                    │ │small                │   │
                    │ │・ドキュメント       │   │
                    │ │  ベクトル化         │   │
                    │ └─────────────────────┘   │
                    └───────────────────────────┘
                                │
                                │ベクトル検索クエリ
                                ▼
                    ┌───────────────────────┐
                    │  Azure AI Search      │
                    │                       │
                    │  index: documents     │
                    │  ・仕様書             │
                    │  ・会社概要           │
                    │  ・顧客一覧           │
                    │  ・ニュース記事       │
                    │  （ハイブリッド検索） │
                    └───────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│                  インフラ管理層                              │
│                                                             │
│  ┌─────────────────┐          ┌──────────────────────────┐ │
│  │  Azure Key Vault │          │  Azure Log Analytics     │ │
│  │                 │          │  Workspace               │ │
│  │ 全APIキー・     │          │                          │ │
│  │ シークレット    │          │  Container Apps のログ   │ │
│  │ を一元管理      │          │  を集約・可視化          │ │
│  └─────────────────┘          └──────────────────────────┘ │
│                                                             │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  Azure Container Registry                            │  │
│  │                                                      │  │
│  │  Botアプリの Dockerイメージを保管                     │  │
│  │  Managed Identity（AcrPull）で認証なしに pull         │  │
│  └──────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

---

## C-02 パイプライン詳細フロー（仕様補完）

```
Teams 発話
    │
    ▼
[Intent Analysis]  ← Azure OpenAI (gpt-4o)
    │ intent: spec_inquiry？
    │ YES
    ▼
[RAG Search]       ← Azure AI Search (ハイブリッド検索)
    │               + Azure OpenAI (text-embedding-3-small)
    │ 関連ドキュメントあり？
    │ YES
    ▼
[Answer Generation] ← Azure OpenAI (gpt-4o)
    │
    ▼
[Teams チャット投稿] ← Bot Framework Adapter
    │
    ▼
[Cosmos DB 保存]    ← utterances / agent_logs
```

---

## C-03 パイプライン詳細フロー（曖昧発言補完）

```
Teams 発話
    │
    ▼
[Intent Analysis]    ← Azure OpenAI (gpt-4o)
    │ intent: ambiguous？
    │ YES
    ▼
[Ambiguity Detect]   ← Azure OpenAI (gpt-4o)
    │ is_ambiguous: true？
    │ YES
    ▼
[Session 作成]       ← Cosmos DB (clarification_sessions)
    │
    ▼
[発言者に 1:1 DM]    ← Bot Framework（Speaker Reference）
    │ 「〇〇とはどういう意味ですか？」
    │
    ▼ 発言者が返信（60秒以内）
    │
[Clarification Summary] ← Azure OpenAI (gpt-4o)
    │
    ▼
[会議チャットに投稿]  ← Bot Framework（Meeting Reference）
    │ 「[明確化] 〇〇さんの発言は〇〇を意味する」
    │
    ▼
[Session 更新]       ← Cosmos DB (status: SUMMARIZED)
```

---

## Terraform ファイル構成

```
infra/
├── main.tf          # プロバイダ設定・リソースグループ
├── variables.tf     # 変数定義（リージョン・SKU・容量など）
├── outputs.tf       # 出力値（URL・エンドポイントなど）
├── container.tf     # Container Registry + Container Apps
├── cognitive.tf     # Azure OpenAI + AI Speech + AI Search
├── cosmos.tf        # Cosmos DB アカウント・データベース・コレクション
├── security.tf      # Managed Identity + Key Vault
├── monitoring.tf    # Log Analytics Workspace
├── backend.tf       # Terraform State 設定（Azure Blob Storage）
└── terraform.tfvars # 実際の変数値（Git管理外）
```

---

## 環境変数（.env）

Container Apps 本体は Key Vault 参照で動作しますが、ローカル開発時は `.env` ファイルで以下を設定します。

| 変数名 | 取得元 |
|---|---|
| `AZURE_OPENAI_ENDPOINT` | `outputs.openai_endpoint` |
| `AZURE_OPENAI_KEY` | Key Vault: `azure-openai-key` |
| `AZURE_OPENAI_DEPLOYMENT` | `gpt-4o`（固定） |
| `AZURE_OPENAI_EMBEDDING_DEPLOYMENT` | `text-embedding-3-small`（固定） |
| `AZURE_SEARCH_ENDPOINT` | `outputs.search_endpoint` |
| `AZURE_SEARCH_KEY` | Key Vault: `azure-search-key` |
| `AZURE_SEARCH_INDEX` | `documents`（固定） |
| `AZURE_SPEECH_KEY` | Key Vault: `azure-speech-key` |
| `AZURE_SPEECH_REGION` | `japaneast`（固定） |
| `COSMOS_ENDPOINT` | `outputs.cosmos_endpoint` |
| `COSMOS_KEY` | Key Vault: `azure-cosmos-key` |
| `MICROSOFT_APP_ID` | Bot Framework 登録 |
| `MICROSOFT_APP_PASSWORD` | Bot Framework 登録 |
