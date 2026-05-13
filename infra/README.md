# インフラ構築手順（Terraform）

このドキュメントでは、MOCHI-kiki が必要とする Azure リソース群を Terraform で構築する手順を説明します。

---

## 目次

1. [構成されるリソース一覧](#構成されるリソース一覧)
2. [前提条件](#前提条件)
3. [ステップ 1: Terraform state 用ストレージを作成する](#ステップ-1-terraform-state-用ストレージを作成する)
4. [ステップ 2: 変数ファイルを準備する](#ステップ-2-変数ファイルを準備する)
5. [ステップ 3: Terraform を初期化する](#ステップ-3-terraform-を初期化する)
6. [ステップ 4: 実行計画を確認する](#ステップ-4-実行計画を確認する)
7. [ステップ 5: リソースを作成する](#ステップ-5-リソースを作成する)
8. [ステップ 6: デプロイ後の設定](#ステップ-6-デプロイ後の設定)
9. [リソースを削除する](#リソースを削除する)
10. [トラブルシューティング](#トラブルシューティング)

---

## 構成されるリソース一覧

| ファイル | リソース | 用途 |
|---|---|---|
| `main.tf` | Resource Group | 全リソースの親グループ |
| `cognitive.tf` | Azure OpenAI (GPT-4o + text-embedding-3-small) | 意図解析・回答生成・埋め込み |
| `cognitive.tf` | Azure AI Speech | 会議音声のリアルタイム文字起こし |
| `cognitive.tf` | Azure AI Search | ドキュメントのベクトル検索（RAG） |
| `cosmos.tf` | Azure Cosmos DB (SQL API) | 発話・会議・セッションデータの永続化 |
| `container.tf` | Azure Container Registry | Bot の Docker イメージ管理 |
| `container.tf` | Azure Container Apps | Bot のサーバーレス実行環境 |
| `security.tf` | Azure Key Vault | API キー・シークレットの一元管理 |
| `security.tf` | User Assigned Managed Identity | Bot が他リソースにアクセスするための ID |
| `monitoring.tf` | Log Analytics Workspace | コンテナログの収集・分析 |

**Cosmos DB コンテナ一覧**

| コンテナ名 | パーティションキー | 内容 |
|---|---|---|
| `utterances` | `/meeting_id` | 会議中の発話ログ |
| `meetings` | `/id` | 会議メタデータ |
| `clarification_sessions` | `/meeting_id` | 曖昧化解消セッション（C-03） |
| `consents` | `/meeting_id` | 録音同意記録 |
| `agent_logs` | `/meeting_id` | エージェント処理ログ |

---

## 前提条件

以下のツールと権限を事前に用意してください。

### 必要なツール

| ツール | バージョン | インストール方法 |
|---|---|---|
| [Terraform](https://developer.hashicorp.com/terraform/install) | >= 1.7 | 公式サイトまたは `winget install HashiCorp.Terraform` |
| [Azure CLI](https://learn.microsoft.com/ja-jp/cli/azure/install-azure-cli) | 最新版 | `winget install Microsoft.AzureCLI` |

### 必要な Azure 権限

Terraform を実行するアカウント（サービスプリンシパルまたはユーザー）に以下のロールが必要です。

- **Contributor**（リソースグループ・全リソースの作成）
- **User Access Administrator**（Managed Identity への Role Assignment 付与）

### Azure CLI でログイン

```bash
az login
az account set --subscription "<サブスクリプション ID>"
```

ログイン中のアカウントを確認します。

```bash
az account show --query "{name:name, id:id, user:user.name}"
```

---

## ステップ 1: Terraform state 用ストレージを作成する

Terraform は実行状態（state）を Azure Blob Storage に保存します。  
以下の手順で **Terraform 実行前に** state 用のリソースを手動で作成します。

```bash
# 変数を設定する（自分の環境に合わせて変更する）
RG_TFSTATE="rg-tfstate"
SA_NAME="mochikiikitfstate"   # グローバルで一意な名前にすること
CONTAINER="tfstate"
LOCATION="japaneast"

# リソースグループを作成
az group create --name $RG_TFSTATE --location $LOCATION

# ストレージアカウントを作成
az storage account create \
  --name $SA_NAME \
  --resource-group $RG_TFSTATE \
  --location $LOCATION \
  --sku Standard_LRS \
  --allow-blob-public-access false

# Blob コンテナを作成
az storage container create \
  --name $CONTAINER \
  --account-name $SA_NAME
```

> **注意**: ストレージアカウント名（`mochikiikitfstate`）は Azure 全体でグローバルに一意である必要があります。  
> 同名が既に使われている場合は別の名前に変更してください。

---

## ステップ 2: 変数ファイルを準備する

`infra/` ディレクトリに移動し、サンプルファイルをコピーします。

```bash
cd infra
cp terraform.tfvars.example terraform.tfvars
```

`terraform.tfvars` を開いて実際の値を入力します。

```hcl
# Azure サブスクリプション ID（必須）
subscription_id = "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"

# デプロイ先リージョン（変更不要）
location = "japaneast"

# リソースグループ名
resource_group_name = "rg-mochi-kiki"

# リソース名のプレフィックス（他と重複しない短い文字列）
prefix = "mochikiki"

# 環境識別子（dev / prod）
environment = "dev"

# Terraform state の保管先（ステップ 1 で作成したリソース）
tf_state_resource_group  = "rg-tfstate"
tf_state_storage_account = "mochikiikitfstate"
tf_state_container       = "tfstate"

# Azure OpenAI のモデル容量（TPM × 1,000）
gpt4o_capacity     = 30
embedding_capacity = 30

# Azure AI Search の SKU（basic / standard / storage_optimized_l1 など）
search_sku = "basic"

# Cosmos DB の整合性レベル
cosmos_consistency_level = "Session"

# Bot コンテナの最小・最大レプリカ数
bot_min_replicas = 1
bot_max_replicas = 3
```

> **重要**: `terraform.tfvars` には機密情報が含まれるため `.gitignore` に追加し、リポジトリにコミットしないでください。

---

## ステップ 3: Terraform を初期化する

`infra/` ディレクトリで以下を実行します。  
`-backend-config` でステップ 1 で作成した state ストレージを指定します。

```bash
terraform init \
  -backend-config="resource_group_name=rg-tfstate" \
  -backend-config="storage_account_name=mochikiikitfstate" \
  -backend-config="container_name=tfstate" \
  -backend-config="key=mochi-kiki.tfstate"
```

成功すると以下のメッセージが表示されます。

```
Terraform has been successfully initialized!
```

---

## ステップ 4: 実行計画を確認する

実際にリソースを作成する前に、何が作成されるかを確認します。

```bash
terraform plan -out=tfplan
```

出力の末尾に表示される `Plan: XX to add, 0 to change, 0 to destroy.` を確認し、  
意図した変更のみが含まれていることを確認してください。

主に以下のリソースが `add` として表示されます。

- `azurerm_resource_group.main`
- `azurerm_cognitive_account.openai` / `azurerm_cognitive_account.speech`
- `azurerm_cognitive_deployment.gpt4o` / `azurerm_cognitive_deployment.embedding`
- `azurerm_search_service.main`
- `azurerm_cosmosdb_account.main` および各コンテナ
- `azurerm_container_registry.main`
- `azurerm_container_app_environment.main` / `azurerm_container_app.bot`
- `azurerm_key_vault.main` および各シークレット
- `azurerm_user_assigned_identity.bot`
- `azurerm_log_analytics_workspace.main`

---

## ステップ 5: リソースを作成する

計画を確認したら `apply` でリソースを作成します。

```bash
terraform apply tfplan
```

または、確認プロンプトを含めて実行する場合は以下のようにします。

```bash
terraform apply
```

`Enter a value:` プロンプトに `yes` と入力すると適用が開始されます。

完了まで **約 10〜20 分** かかります。完了後、以下のような出力値（outputs）が表示されます。

```
Outputs:

acr_login_server         = "mochikiikiacr<env>.azurecr.io"
container_app_url        = "https://mochikiki-bot-<env>.<region>.azurecontainerapps.io"
cosmos_endpoint          = "https://mochikiki-cosmos-<env>.documents.azure.com:443/"
key_vault_uri            = "https://mochikiki-kv-<env>.vault.azure.net/"
managed_identity_client_id = "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
openai_endpoint          = "https://mochikiki-oai-<env>.openai.azure.com/"
resource_group_name      = "rg-mochi-kiki"
search_endpoint          = "https://mochikiki-search-<env>.search.windows.net"
speech_endpoint          = "japaneast"
```

outputs は後から以下のコマンドで再確認できます。

```bash
terraform output
```

---

## ステップ 6: デプロイ後の設定

リソース作成後、以下の手動設定が必要です。

### 6-1. Bot Framework の Messaging Endpoint を設定する

[Azure Portal](https://portal.azure.com) または [Bot Framework Developer Portal](https://dev.botframework.com) で、  
Teams Bot のメッセージングエンドポイントを次の URL に設定します。

```
https://<container_app_url>/api/messages
```

`container_app_url` は `terraform output container_app_url` で確認できます。

### 6-2. Bot の Docker イメージをプッシュする

初回デプロイ後、プレースホルダイメージを本番イメージに置き換えます。

```bash
# ACR にログイン
az acr login --name <acr_login_server>

# イメージをビルドしてプッシュ
docker build -t <acr_login_server>/mochi-kiki-bot:latest ../
docker push <acr_login_server>/mochi-kiki-bot:latest
```

その後、Container Apps のイメージを更新します。

```bash
az containerapp update \
  --name mochikiki-bot-dev \
  --resource-group rg-mochi-kiki \
  --image <acr_login_server>/mochi-kiki-bot:latest
```

### 6-3. アプリ設定に環境変数を追加する

Bot Framework の `MICROSOFT_APP_ID` と `MICROSOFT_APP_PASSWORD` は Key Vault に格納されていません。  
Container Apps の環境変数として手動で設定してください。

```bash
az containerapp secret set \
  --name mochikiki-bot-dev \
  --resource-group rg-mochi-kiki \
  --secrets \
    ms-app-id=<MICROSOFT_APP_ID> \
    ms-app-password=<MICROSOFT_APP_PASSWORD>

az containerapp update \
  --name mochikiki-bot-dev \
  --resource-group rg-mochi-kiki \
  --set-env-vars \
    MICROSOFT_APP_ID=secretref:ms-app-id \
    MICROSOFT_APP_PASSWORD=secretref:ms-app-password
```

### 6-4. AI Search インデックスを作成する

RAG 検索に使うインデックスとサンプルドキュメントを登録します。

```bash
cd ../scripts
python3 setup_search_index.py
```

---

## リソースを削除する

全リソースを削除する場合は以下を実行します。

```bash
terraform destroy
```

`Enter a value:` プロンプトに `yes` と入力すると削除が開始されます。

> **注意**:  
> - Key Vault と Azure OpenAI は **ソフト削除**が有効になっています。`purge_soft_delete_on_destroy = true` の設定により `destroy` 時に完全削除されますが、同名リソースを再作成する場合は数分待つ必要がある場合があります。  
> - Terraform state 用のリソースグループ（`rg-tfstate`）は `destroy` の対象外です。不要であれば手動で削除してください。

---

## トラブルシューティング

### `Error: A resource with the ID already exists`

soft-delete 済みの Key Vault または OpenAI リソースが残っている場合に発生します。  
以下のコマンドで完全削除（purge）してから再実行してください。

```bash
# Key Vault の場合
az keyvault purge --name <vault-name> --location japaneast

# OpenAI の場合
az cognitiveservices account purge \
  --name <account-name> \
  --resource-group <resource-group> \
  --location japaneast
```

### `Error: insufficient quota`

Azure OpenAI のクォータ不足です。  
[Azure Portal > Quotas](https://portal.azure.com/#view/Microsoft_Azure_ProjectOxford/CognitiveServicesHub/~/OpenAI) でクォータを確認し、  
`gpt4o_capacity` または `embedding_capacity` の値を小さくしてから再実行してください。

### `Error: Backend configuration changed`

バックエンド設定が変わった場合は `-reconfigure` フラグを付けて再 init します。

```bash
terraform init -reconfigure \
  -backend-config="resource_group_name=rg-tfstate" \
  -backend-config="storage_account_name=mochikiikitfstate" \
  -backend-config="container_name=tfstate" \
  -backend-config="key=mochi-kiki.tfstate"
```

### state のロックが解除されない

別のプロセスが `terraform apply` を実行中または異常終了した場合にロックが残ることがあります。

```bash
terraform force-unlock <LOCK_ID>
```

`LOCK_ID` はエラーメッセージ内に表示されます。
