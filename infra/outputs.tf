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

output "recall_webhook_url" {
  description = <<-EOT
    Recall.ai の Webhook URL（HMAC 署名検証あり）。
    bot 作成時 recording_config.realtime_endpoints[].url または環境変数
    RECALL_WEBHOOK_PUBLIC_URL に設定する。WS 経路を併用する場合は
    本値ではなく recall_ws_url を推奨。
  EOT
  value       = "https://${azurerm_container_app.bot.latest_revision_fqdn}/api/recall/webhook"
}

output "recall_webhook_url_legacy" {
  description = <<-EOT
    DEPRECATED. 旧簡易版ルータ /api/recall/transcript の URL（**署名検証なし**）。
    Phase 6 で削除予定。新規設定で使わないこと。
  EOT
  value       = "https://${azurerm_container_app.bot.latest_revision_fqdn}/api/recall/transcript"
}

output "recall_ws_url" {
  description = "Recall.ai の realtime WebSocket URL（bot 作成時 recording_config.realtime_endpoints[].url または環境変数 RECALL_WS_PUBLIC_URL に設定する）"
  value       = "wss://${azurerm_container_app.bot.latest_revision_fqdn}/api/recall/ws"
}
