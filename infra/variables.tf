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

variable "search_sku" {
  description = "Azure AI Search の SKU"
  type        = string
  default     = "basic"
}

variable "cosmos_consistency_level" {
  description = "Cosmos DB の整合性レベル"
  type        = string
  default     = "Session"
}

variable "acr_sku" {
  description = "Azure Container Registry の SKU"
  type        = string
  default     = "Basic"
}

variable "bot_image" {
  description = "Container Apps で動かす Bot の Docker イメージ（初期デプロイ用プレースホルダ）"
  type        = string
  default     = "mcr.microsoft.com/azuredocs/containerapps-helloworld:latest"
}

variable "bot_min_replicas" {
  description = "Bot Container Apps の最小レプリカ数"
  type    = number
  default = 1
}

variable "bot_max_replicas" {
  description = "Bot Container Apps の最大レプリカ数"
  type    = number
  default = 3
}
