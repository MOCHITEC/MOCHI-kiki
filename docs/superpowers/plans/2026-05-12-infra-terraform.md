# インフラ構築（Terraform）実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** MOCHI-kiki が動作するために必要な Azure リソース全体を Terraform で定義し、`terraform plan` が通る状態にする（`apply` は Azure 接続が必要なため手動実行を前提とする）。

**Architecture:** フラット構成（モジュールなし）で可読性を優先する。ファイルをリソース種別ごとに分割し、変数は `variables.tf` に集約、出力値（エンドポイント・キー）は `outputs.tf` に集約する。Terraform state は Azure Storage（リモートバックエンド）に保存する前提で `backend.tf` に設定を記述するが、バックエンド用 Storage Account の作成は事前手動作業とする。

**Tech Stack:** Terraform >= 1.7, azurerm provider ~> 3.100

---

## ファイル構成

```
infra/
├── backend.tf                  # Terraform リモートバックエンド設定（Azure Storage）
├── main.tf                     # Provider 設定・Resource Group
├── variables.tf                # 全入力変数の定義
├── outputs.tf                  # 全出力値（エンドポイント・名前）
├── cognitive.tf                # Azure OpenAI / AI Speech / AI Search
├── cosmos.tf                   # Azure Cosmos DB（NoSQL API）
├── container.tf                # Azure Container Registry / Container Apps
├── security.tf                 # Azure Key Vault / Managed Identity
├── monitoring.tf               # Log Analytics Workspace
└── terraform.tfvars.example    # 変数値のサンプル（secrets は含まない）
```

---

### Task 1: infra ディレクトリと Terraform バックエンド・プロバイダ設定

**Files:**
- Create: `infra/backend.tf`
- Create: `infra/main.tf`
- Create: `infra/variables.tf`（全変数定義）
- Create: `infra/terraform.tfvars.example`

- [ ] **Step 1: infra ディレクトリを作成する**

```bash
mkdir -p infra
```

- [ ] **Step 2: infra/variables.tf を作成する（全変数を一括定義）**

```hcl
# infra/variables.tf

variable "subscription_id" {
  description = "Azure Subscription ID"
  type        = string
}

variable "location" {
  description = "Azure リージョン"
  type        = string
  default     = "japaneast"
}

variable "resource_group_name" {
  description = "リソースグループ名"
  type        = string
  default     = "rg-mochi-kiki"
}

variable "prefix" {
  description = "リソース名のプレフィックス（一意性確保のため）"
  type        = string
  default     = "mochikiki"
}

variable "environment" {
  description = "デプロイ環境（dev / prod）"
  type        = string
  default     = "dev"
}

# Terraform State バックエンド用（backend.tf で参照）
variable "tf_state_resource_group" {
  description = "Terraform state を保存する Storage Account のリソースグループ名"
  type        = string
  default     = "rg-tfstate"
}

variable "tf_state_storage_account" {
  description = "Terraform state を保存する Storage Account 名"
  type        = string
  default     = "mochikiikitfstate"
}

variable "tf_state_container" {
  description = "Terraform state を保存する Blob コンテナ名"
  type        = string
  default     = "tfstate"
}

# Azure OpenAI
variable "openai_sku" {
  description = "Azure OpenAI の SKU"
  type        = string
  default     = "S0"
}

variable "gpt4o_capacity" {
  description = "GPT-4o デプロイの TPM 上限（1,000 単位）"
  type        = number
  default     = 30
}

variable "embedding_capacity" {
  description = "text-embedding-3-small の TPM 上限（1,000 単位）"
  type        = number
  default     = 30
}

# Azure AI Search
variable "search_sku" {
  description = "Azure AI Search の SKU"
  type        = string
  default     = "basic"
}

# Azure Cosmos DB
variable "cosmos_consistency_level" {
  description = "Cosmos DB の整合性レベル"
  type        = string
  default     = "Session"
}

# Azure Container Registry
variable "acr_sku" {
  description = "Azure Container Registry の SKU"
  type        = string
  default     = "Basic"
}

# Azure Container Apps
variable "bot_image" {
  description = "Container Apps で動かす Bot の Docker イメージ（初期デプロイ用プレースホルダ）"
  type        = string
  default     = "mcr.microsoft.com/azuredocs/containerapps-helloworld:latest"
}

variable "bot_min_replicas" {
  type    = number
  default = 1
}

variable "bot_max_replicas" {
  type    = number
  default = 3
}
```

- [ ] **Step 3: infra/backend.tf を作成する**

```hcl
# infra/backend.tf
# NOTE: backend ブロック内では変数を使用できないため、
#       実際の値は terraform init 時に -backend-config フラグで渡す。
#       または terraform.tfvars に storage_account_name 等を直書きして使う。

terraform {
  required_version = ">= 1.7"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 3.100"
    }
  }

  backend "azurerm" {
    # terraform init 時に以下を -backend-config で渡す（または backend.hcl を使う）
    # resource_group_name  = "rg-tfstate"
    # storage_account_name = "mochikiikitfstate"
    # container_name       = "tfstate"
    # key                  = "mochi-kiki.tfstate"
  }
}
```

- [ ] **Step 4: infra/main.tf を作成する（Provider + Resource Group）**

```hcl
# infra/main.tf

provider "azurerm" {
  features {
    key_vault {
      purge_soft_delete_on_destroy    = true
      recover_soft_deleted_key_vaults = true
    }
    cognitive_account {
      purge_soft_delete_on_destroy = true
    }
  }
  subscription_id = var.subscription_id
}

data "azurerm_client_config" "current" {}

resource "azurerm_resource_group" "main" {
  name     = var.resource_group_name
  location = var.location

  tags = {
    environment = var.environment
    project     = "mochi-kiki"
  }
}
```

- [ ] **Step 5: infra/terraform.tfvars.example を作成する**

```hcl
# infra/terraform.tfvars.example
# このファイルをコピーして terraform.tfvars を作成し、実際の値を入力する。
# terraform.tfvars は .gitignore に追加してコミットしないこと。

subscription_id     = "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
location            = "japaneast"
resource_group_name = "rg-mochi-kiki"
prefix              = "mochikiki"
environment         = "dev"

# Terraform State バックエンド（terraform init 前に手動で作成しておく）
tf_state_resource_group  = "rg-tfstate"
tf_state_storage_account = "mochikiikitfstate"
tf_state_container       = "tfstate"

# Azure OpenAI
openai_sku       = "S0"
gpt4o_capacity   = 30
embedding_capacity = 30

# Azure AI Search
search_sku = "basic"

# Azure Cosmos DB
cosmos_consistency_level = "Session"

# Azure Container Registry
acr_sku = "Basic"

# Azure Container Apps
bot_min_replicas = 1
bot_max_replicas = 3
```

- [ ] **Step 6: .gitignore に Terraform 機密ファイルを追加する**

プロジェクトルートの `.gitignore` を作成または編集する：

```gitignore
# Terraform
infra/.terraform/
infra/*.tfstate
infra/*.tfstate.backup
infra/*.tfvars
infra/.terraform.lock.hcl

# Python
__pycache__/
*.py[cod]
.venv/
dist/
*.egg-info/

# Environment
.env
.env.local
```

- [ ] **Step 7: コミット**

```bash
git add infra/ .gitignore
git commit -m "chore(infra): initialize Terraform project structure with provider and backend config"
```

---

### Task 2: 監視・セキュリティリソースの定義

**Files:**
- Create: `infra/monitoring.tf`
- Create: `infra/security.tf`

- [ ] **Step 1: infra/monitoring.tf を作成する**

```hcl
# infra/monitoring.tf

resource "azurerm_log_analytics_workspace" "main" {
  name                = "${var.prefix}-law-${var.environment}"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  sku                 = "PerGB2018"
  retention_in_days   = 30

  tags = azurerm_resource_group.main.tags
}
```

- [ ] **Step 2: infra/security.tf を作成する**

```hcl
# infra/security.tf

# Managed Identity（Container Apps が他リソースにアクセスするために使う）
resource "azurerm_user_assigned_identity" "bot" {
  name                = "${var.prefix}-id-bot-${var.environment}"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name

  tags = azurerm_resource_group.main.tags
}

# Key Vault（API キー・シークレットの保管）
resource "azurerm_key_vault" "main" {
  name                        = "${var.prefix}-kv-${var.environment}"
  location                    = azurerm_resource_group.main.location
  resource_group_name         = azurerm_resource_group.main.name
  tenant_id                   = data.azurerm_client_config.current.tenant_id
  sku_name                    = "standard"
  soft_delete_retention_days  = 7
  purge_protection_enabled    = false

  tags = azurerm_resource_group.main.tags
}

# Key Vault アクセスポリシー: Terraform 実行者（自分）
resource "azurerm_key_vault_access_policy" "terraform_operator" {
  key_vault_id = azurerm_key_vault.main.id
  tenant_id    = data.azurerm_client_config.current.tenant_id
  object_id    = data.azurerm_client_config.current.object_id

  secret_permissions = [
    "Get", "List", "Set", "Delete", "Purge", "Recover"
  ]
}

# Key Vault アクセスポリシー: Bot の Managed Identity
resource "azurerm_key_vault_access_policy" "bot_identity" {
  key_vault_id = azurerm_key_vault.main.id
  tenant_id    = data.azurerm_client_config.current.tenant_id
  object_id    = azurerm_user_assigned_identity.bot.principal_id

  secret_permissions = ["Get", "List"]
}
```

- [ ] **Step 3: コミット**

```bash
git add infra/monitoring.tf infra/security.tf
git commit -m "chore(infra): add Log Analytics and Key Vault / Managed Identity resources"
```

---

### Task 3: AI・コグニティブサービスの定義

**Files:**
- Create: `infra/cognitive.tf`

- [ ] **Step 1: infra/cognitive.tf を作成する**

```hcl
# infra/cognitive.tf

# ── Azure OpenAI ──────────────────────────────────────────────────────────────

resource "azurerm_cognitive_account" "openai" {
  name                = "${var.prefix}-oai-${var.environment}"
  location            = var.location
  resource_group_name = azurerm_resource_group.main.name
  kind                = "OpenAI"
  sku_name            = var.openai_sku

  tags = azurerm_resource_group.main.tags
}

resource "azurerm_cognitive_deployment" "gpt4o" {
  name                 = "gpt-4o"
  cognitive_account_id = azurerm_cognitive_account.openai.id

  model {
    format  = "OpenAI"
    name    = "gpt-4o"
    version = "2024-11-20"
  }

  scale {
    type     = "Standard"
    capacity = var.gpt4o_capacity
  }
}

resource "azurerm_cognitive_deployment" "embedding" {
  name                 = "text-embedding-3-small"
  cognitive_account_id = azurerm_cognitive_account.openai.id

  model {
    format  = "OpenAI"
    name    = "text-embedding-3-small"
    version = "1"
  }

  scale {
    type     = "Standard"
    capacity = var.embedding_capacity
  }
}

# Key Vault にエンドポイントとキーを保存する
resource "azurerm_key_vault_secret" "openai_endpoint" {
  name         = "azure-openai-endpoint"
  value        = azurerm_cognitive_account.openai.endpoint
  key_vault_id = azurerm_key_vault.main.id

  depends_on = [azurerm_key_vault_access_policy.terraform_operator]
}

resource "azurerm_key_vault_secret" "openai_key" {
  name         = "azure-openai-key"
  value        = azurerm_cognitive_account.openai.primary_access_key
  key_vault_id = azurerm_key_vault.main.id

  depends_on = [azurerm_key_vault_access_policy.terraform_operator]
}

# ── Azure AI Speech ───────────────────────────────────────────────────────────

resource "azurerm_cognitive_account" "speech" {
  name                = "${var.prefix}-speech-${var.environment}"
  location            = var.location
  resource_group_name = azurerm_resource_group.main.name
  kind                = "SpeechServices"
  sku_name            = "S0"

  tags = azurerm_resource_group.main.tags
}

resource "azurerm_key_vault_secret" "speech_key" {
  name         = "azure-speech-key"
  value        = azurerm_cognitive_account.speech.primary_access_key
  key_vault_id = azurerm_key_vault.main.id

  depends_on = [azurerm_key_vault_access_policy.terraform_operator]
}

resource "azurerm_key_vault_secret" "speech_region" {
  name         = "azure-speech-region"
  value        = azurerm_cognitive_account.speech.location
  key_vault_id = azurerm_key_vault.main.id

  depends_on = [azurerm_key_vault_access_policy.terraform_operator]
}

# ── Azure AI Search ───────────────────────────────────────────────────────────

resource "azurerm_search_service" "main" {
  name                = "${var.prefix}-search-${var.environment}"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  sku                 = var.search_sku

  tags = azurerm_resource_group.main.tags
}

resource "azurerm_key_vault_secret" "search_endpoint" {
  name         = "azure-search-endpoint"
  value        = "https://${azurerm_search_service.main.name}.search.windows.net"
  key_vault_id = azurerm_key_vault.main.id

  depends_on = [azurerm_key_vault_access_policy.terraform_operator]
}

resource "azurerm_key_vault_secret" "search_key" {
  name         = "azure-search-key"
  value        = azurerm_search_service.main.primary_key
  key_vault_id = azurerm_key_vault.main.id

  depends_on = [azurerm_key_vault_access_policy.terraform_operator]
}
```

- [ ] **Step 2: コミット**

```bash
git add infra/cognitive.tf
git commit -m "chore(infra): add Azure OpenAI (GPT-4o + embedding), AI Speech, and AI Search resources"
```

---

### Task 4: Cosmos DB の定義

**Files:**
- Create: `infra/cosmos.tf`

- [ ] **Step 1: infra/cosmos.tf を作成する**

```hcl
# infra/cosmos.tf

resource "azurerm_cosmosdb_account" "main" {
  name                = "${var.prefix}-cosmos-${var.environment}"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  offer_type          = "Standard"
  kind                = "GlobalDocumentDB"

  consistency_policy {
    consistency_level = var.cosmos_consistency_level
  }

  geo_location {
    location          = azurerm_resource_group.main.location
    failover_priority = 0
  }

  tags = azurerm_resource_group.main.tags
}

resource "azurerm_cosmosdb_sql_database" "meeting_db" {
  name                = "meeting_db"
  resource_group_name = azurerm_resource_group.main.name
  account_name        = azurerm_cosmosdb_account.main.name
}

resource "azurerm_cosmosdb_sql_container" "utterances" {
  name                = "utterances"
  resource_group_name = azurerm_resource_group.main.name
  account_name        = azurerm_cosmosdb_account.main.name
  database_name       = azurerm_cosmosdb_sql_database.meeting_db.name
  partition_key_path  = "/meeting_id"

  indexing_policy {
    indexing_mode = "consistent"

    included_path {
      path = "/*"
    }
  }
}

resource "azurerm_cosmosdb_sql_container" "meetings" {
  name                = "meetings"
  resource_group_name = azurerm_resource_group.main.name
  account_name        = azurerm_cosmosdb_account.main.name
  database_name       = azurerm_cosmosdb_sql_database.meeting_db.name
  partition_key_path  = "/id"

  indexing_policy {
    indexing_mode = "consistent"

    included_path {
      path = "/*"
    }
  }
}

resource "azurerm_cosmosdb_sql_container" "clarification_sessions" {
  name                = "clarification_sessions"
  resource_group_name = azurerm_resource_group.main.name
  account_name        = azurerm_cosmosdb_account.main.name
  database_name       = azurerm_cosmosdb_sql_database.meeting_db.name
  partition_key_path  = "/meeting_id"

  indexing_policy {
    indexing_mode = "consistent"

    included_path {
      path = "/*"
    }
  }
}

resource "azurerm_cosmosdb_sql_container" "consents" {
  name                = "consents"
  resource_group_name = azurerm_resource_group.main.name
  account_name        = azurerm_cosmosdb_account.main.name
  database_name       = azurerm_cosmosdb_sql_database.meeting_db.name
  partition_key_path  = "/meeting_id"

  indexing_policy {
    indexing_mode = "consistent"

    included_path {
      path = "/*"
    }
  }
}

resource "azurerm_cosmosdb_sql_container" "agent_logs" {
  name                = "agent_logs"
  resource_group_name = azurerm_resource_group.main.name
  account_name        = azurerm_cosmosdb_account.main.name
  database_name       = azurerm_cosmosdb_sql_database.meeting_db.name
  partition_key_path  = "/meeting_id"

  indexing_policy {
    indexing_mode = "consistent"

    included_path {
      path = "/*"
    }
  }
}

# Key Vault にエンドポイントとキーを保存する
resource "azurerm_key_vault_secret" "cosmos_endpoint" {
  name         = "azure-cosmos-endpoint"
  value        = azurerm_cosmosdb_account.main.endpoint
  key_vault_id = azurerm_key_vault.main.id

  depends_on = [azurerm_key_vault_access_policy.terraform_operator]
}

resource "azurerm_key_vault_secret" "cosmos_key" {
  name         = "azure-cosmos-key"
  value        = azurerm_cosmosdb_account.main.primary_key
  key_vault_id = azurerm_key_vault.main.id

  depends_on = [azurerm_key_vault_access_policy.terraform_operator]
}
```

- [ ] **Step 2: コミット**

```bash
git add infra/cosmos.tf
git commit -m "chore(infra): add Cosmos DB account with meeting_db database and 5 containers"
```

---

### Task 5: コンテナ（ACR・Container Apps）の定義

**Files:**
- Create: `infra/container.tf`

- [ ] **Step 1: infra/container.tf を作成する**

```hcl
# infra/container.tf

# ── Azure Container Registry ──────────────────────────────────────────────────

resource "azurerm_container_registry" "main" {
  name                = "${var.prefix}acr${var.environment}"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  sku                 = var.acr_sku
  admin_enabled       = true

  tags = azurerm_resource_group.main.tags
}

# Managed Identity に ACR への pull 権限を付与する
resource "azurerm_role_assignment" "bot_acr_pull" {
  scope                = azurerm_container_registry.main.id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_user_assigned_identity.bot.principal_id
}

# ── Azure Container Apps ──────────────────────────────────────────────────────

resource "azurerm_container_app_environment" "main" {
  name                       = "${var.prefix}-cae-${var.environment}"
  location                   = azurerm_resource_group.main.location
  resource_group_name        = azurerm_resource_group.main.name
  log_analytics_workspace_id = azurerm_log_analytics_workspace.main.id

  tags = azurerm_resource_group.main.tags
}

resource "azurerm_container_app" "bot" {
  name                         = "${var.prefix}-bot-${var.environment}"
  container_app_environment_id = azurerm_container_app_environment.main.id
  resource_group_name          = azurerm_resource_group.main.name
  revision_mode                = "Single"

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.bot.id]
  }

  registry {
    server   = azurerm_container_registry.main.login_server
    identity = azurerm_user_assigned_identity.bot.id
  }

  template {
    min_replicas = var.bot_min_replicas
    max_replicas = var.bot_max_replicas

    container {
      name   = "bot"
      image  = var.bot_image
      cpu    = 0.5
      memory = "1Gi"

      # 環境変数は Key Vault 参照で注入する（値はデプロイ時に差し替え）
      env {
        name  = "PORT"
        value = "3978"
      }
      env {
        name  = "AZURE_KEYVAULT_URI"
        value = azurerm_key_vault.main.vault_uri
      }
    }
  }

  ingress {
    external_enabled = true
    target_port      = 3978

    traffic_weight {
      percentage      = 100
      latest_revision = true
    }
  }

  tags = azurerm_resource_group.main.tags
}

# Key Vault に ACR のログイン情報を保存する
resource "azurerm_key_vault_secret" "acr_server" {
  name         = "acr-login-server"
  value        = azurerm_container_registry.main.login_server
  key_vault_id = azurerm_key_vault.main.id

  depends_on = [azurerm_key_vault_access_policy.terraform_operator]
}
```

- [ ] **Step 2: コミット**

```bash
git add infra/container.tf
git commit -m "chore(infra): add ACR and Container Apps with Managed Identity and ingress config"
```

---

### Task 6: outputs.tf の定義と terraform validate

**Files:**
- Create: `infra/outputs.tf`

- [ ] **Step 1: infra/outputs.tf を作成する**

```hcl
# infra/outputs.tf

output "resource_group_name" {
  description = "リソースグループ名"
  value       = azurerm_resource_group.main.name
}

output "key_vault_uri" {
  description = "Key Vault の URI"
  value       = azurerm_key_vault.main.vault_uri
}

output "acr_login_server" {
  description = "ACR のログインサーバー名"
  value       = azurerm_container_registry.main.login_server
}

output "container_app_url" {
  description = "Bot の外部 URL（Bot Framework の Messaging Endpoint に設定する）"
  value       = "https://${azurerm_container_app.bot.latest_revision_fqdn}"
}

output "openai_endpoint" {
  description = "Azure OpenAI のエンドポイント"
  value       = azurerm_cognitive_account.openai.endpoint
}

output "speech_endpoint" {
  description = "Azure AI Speech のリージョン"
  value       = azurerm_cognitive_account.speech.location
}

output "search_endpoint" {
  description = "Azure AI Search のエンドポイント"
  value       = "https://${azurerm_search_service.main.name}.search.windows.net"
}

output "cosmos_endpoint" {
  description = "Cosmos DB のエンドポイント"
  value       = azurerm_cosmosdb_account.main.endpoint
}

output "managed_identity_client_id" {
  description = "Bot の Managed Identity クライアント ID（Container Apps の認証に使う）"
  value       = azurerm_user_assigned_identity.bot.client_id
}
```

- [ ] **Step 2: terraform init を実行する（バックエンドなしのローカルモードで）**

```bash
cd infra
terraform init -backend=false
```

Expected:
```
Terraform has been successfully initialized!
```

- [ ] **Step 3: terraform validate を実行する**

```bash
terraform validate
```

Expected:
```
Success! The configuration is valid.
```

- [ ] **Step 4: terraform plan をローカルモードで実行する（エラーチェック）**

```bash
terraform plan -var="subscription_id=00000000-0000-0000-0000-000000000000"
```

Expected: エラーなし（リソースが約 25〜30 件表示される）

- [ ] **Step 5: コミット**

```bash
cd ..
git add infra/outputs.tf
git commit -m "chore(infra): add outputs and verify terraform validate passes"
```

---

## インフラ計画 完成チェックリスト（自己レビュー）

| 要件 | 対応ファイル | 実装済みか |
|------|------------|-----------|
| Azure Container Apps（ハッカソン必須） | container.tf | ✅ |
| Azure Container Registry | container.tf | ✅ |
| Azure OpenAI GPT-4o | cognitive.tf | ✅ |
| text-embedding-3-small | cognitive.tf | ✅ |
| Azure AI Speech | cognitive.tf | ✅ |
| Azure AI Search | cognitive.tf | ✅ |
| Azure Cosmos DB + 5コンテナ | cosmos.tf | ✅ |
| Azure Key Vault | security.tf | ✅ |
| Managed Identity（Bot用） | security.tf | ✅ |
| Log Analytics | monitoring.tf | ✅ |
| terraform validate が通る | outputs.tf + Task 6 | ✅ |
| 機密情報が .gitignore で除外される | Task 1 Step 6 | ✅ |

**手動事前作業（terraform apply 前に必要）:**
1. Terraform state 用 Storage Account を Azure Portal または Azure CLI で作成する
2. Bot Framework アプリを Entra ID で登録し、`MICROSOFT_APP_ID` / `MICROSOFT_APP_PASSWORD` を取得する
3. Graph API アクセス用アプリ登録（`GRAPH_CLIENT_ID` / `GRAPH_CLIENT_SECRET`）
4. `terraform init -backend-config=...` でリモートバックエンドを設定する

**apply コマンド（手動実行）:**
```bash
cd infra
terraform init \
  -backend-config="resource_group_name=rg-tfstate" \
  -backend-config="storage_account_name=mochikiikitfstate" \
  -backend-config="container_name=tfstate" \
  -backend-config="key=mochi-kiki.tfstate"

cp terraform.tfvars.example terraform.tfvars
# terraform.tfvars を編集して実際の subscription_id 等を入力する

terraform plan
terraform apply
```
