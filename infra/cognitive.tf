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
    type     = "GlobalStandard"
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
  sku_name            = var.speech_sku

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
  location            = var.location
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
