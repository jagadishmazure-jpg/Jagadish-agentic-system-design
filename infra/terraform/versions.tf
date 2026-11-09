terraform {
  required_version = ">= 1.9.0"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 5.13"
    }
    azapi = {
      source  = "Azure/azapi"
      version = "~> 2.5"
    }
  }
}
