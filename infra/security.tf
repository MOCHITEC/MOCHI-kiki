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
