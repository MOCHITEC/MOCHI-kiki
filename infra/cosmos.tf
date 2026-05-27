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
  partition_key_paths = ["/meeting_id"]

  indexing_policy {
    indexing_mode = "consistent"

    included_path {
      path = "/*"
    }
  }

  # コスト最適化: manual 400 RU 固定よりアイドル時に最小 100 RU まで自動的に下がる
  # autoscale を使う。idle で 5 コンテナ合計 ~$73/mo の削減 (2026-05-27)。
  autoscale_settings {
    max_throughput = 1000
  }
}

resource "azurerm_cosmosdb_sql_container" "meetings" {
  name                = "meetings"
  resource_group_name = azurerm_resource_group.main.name
  account_name        = azurerm_cosmosdb_account.main.name
  database_name       = azurerm_cosmosdb_sql_database.meeting_db.name
  partition_key_paths = ["/id"]

  indexing_policy {
    indexing_mode = "consistent"

    included_path {
      path = "/*"
    }
  }

  # コスト最適化: manual 400 RU 固定よりアイドル時に最小 100 RU まで自動的に下がる
  # autoscale を使う。idle で 5 コンテナ合計 ~$73/mo の削減 (2026-05-27)。
  autoscale_settings {
    max_throughput = 1000
  }
}

resource "azurerm_cosmosdb_sql_container" "clarification_sessions" {
  name                = "clarification_sessions"
  resource_group_name = azurerm_resource_group.main.name
  account_name        = azurerm_cosmosdb_account.main.name
  database_name       = azurerm_cosmosdb_sql_database.meeting_db.name
  partition_key_paths = ["/meeting_id"]

  indexing_policy {
    indexing_mode = "consistent"

    included_path {
      path = "/*"
    }
  }

  # コスト最適化: manual 400 RU 固定よりアイドル時に最小 100 RU まで自動的に下がる
  # autoscale を使う。idle で 5 コンテナ合計 ~$73/mo の削減 (2026-05-27)。
  autoscale_settings {
    max_throughput = 1000
  }
}

resource "azurerm_cosmosdb_sql_container" "consents" {
  name                = "consents"
  resource_group_name = azurerm_resource_group.main.name
  account_name        = azurerm_cosmosdb_account.main.name
  database_name       = azurerm_cosmosdb_sql_database.meeting_db.name
  partition_key_paths = ["/meeting_id"]

  indexing_policy {
    indexing_mode = "consistent"

    included_path {
      path = "/*"
    }
  }

  # コスト最適化: manual 400 RU 固定よりアイドル時に最小 100 RU まで自動的に下がる
  # autoscale を使う。idle で 5 コンテナ合計 ~$73/mo の削減 (2026-05-27)。
  autoscale_settings {
    max_throughput = 1000
  }
}

resource "azurerm_cosmosdb_sql_container" "agent_logs" {
  name                = "agent_logs"
  resource_group_name = azurerm_resource_group.main.name
  account_name        = azurerm_cosmosdb_account.main.name
  database_name       = azurerm_cosmosdb_sql_database.meeting_db.name
  partition_key_paths = ["/meeting_id"]

  indexing_policy {
    indexing_mode = "consistent"

    included_path {
      path = "/*"
    }
  }

  # コスト最適化: manual 400 RU 固定よりアイドル時に最小 100 RU まで自動的に下がる
  # autoscale を使う。idle で 5 コンテナ合計 ~$73/mo の削減 (2026-05-27)。
  autoscale_settings {
    max_throughput = 1000
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
