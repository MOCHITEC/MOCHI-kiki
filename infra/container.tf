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
    # WebSocket Upgrade を確実に通すため明示。
    # http: HTTP/1.1（WS は HTTP/1.1 upgrade で確立される）
    transport = "http"

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
