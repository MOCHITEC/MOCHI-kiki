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

# 全 Azure リソースの親リソースグループ。このプロジェクトの全リソースはここに属する。
resource "azurerm_resource_group" "main" {
  name     = var.resource_group_name
  location = var.location

  tags = {
    environment = var.environment
    project     = "mochi-kiki"
  }
}
