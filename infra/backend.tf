# infra/backend.tf
terraform {
  required_version = ">= 1.7"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 3.100"
    }
  }

  backend "azurerm" {
    # terraform init 時に以下を -backend-config で渡す
    # resource_group_name  = "rg-tfstate"
    # storage_account_name = "mochikiikitfstate"
    # container_name       = "tfstate"
    # key                  = "mochi-kiki.tfstate"
  }
}
