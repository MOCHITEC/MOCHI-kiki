# infra/monitoring.tf

resource "azurerm_log_analytics_workspace" "main" {
  name                = "${var.prefix}-law-${var.environment}"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  sku                 = "PerGB2018"
  retention_in_days   = 30

  tags = azurerm_resource_group.main.tags
}
