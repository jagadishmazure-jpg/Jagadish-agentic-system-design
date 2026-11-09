# Offline plan tests: mocked providers, no Azure credentials, nothing created.
#   terraform init -backend=false && terraform test
mock_provider "azurerm" {
  mock_data "azurerm_client_config" {
    defaults = {
      tenant_id       = "00000000-0000-0000-0000-000000000001"
      subscription_id = "00000000-0000-0000-0000-000000000002"
      object_id       = "00000000-0000-0000-0000-000000000003"
    }
  }
  mock_resource "azurerm_container_app" {
    defaults = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000002/resourceGroups/rg/providers/Microsoft.App/containerApps/ca"
    }
  }
  mock_resource "azurerm_cognitive_account" {
    defaults = {
      id       = "/subscriptions/00000000-0000-0000-0000-000000000002/resourceGroups/rg/providers/Microsoft.CognitiveServices/accounts/aif"
      endpoint = "https://aif.cognitiveservices.azure.com/"
    }
  }
  mock_resource "azurerm_key_vault" {
    defaults = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000002/resourceGroups/rg/providers/Microsoft.KeyVault/vaults/kv"
    }
  }
  mock_resource "azurerm_log_analytics_workspace" {
    defaults = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000002/resourceGroups/rg/providers/Microsoft.OperationalInsights/workspaces/log"
    }
  }
  mock_resource "azurerm_container_app_environment" {
    defaults = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000002/resourceGroups/rg/providers/Microsoft.App/managedEnvironments/cae"
    }
  }
  mock_resource "azurerm_user_assigned_identity" {
    defaults = {
      id           = "/subscriptions/00000000-0000-0000-0000-000000000002/resourceGroups/rg/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id"
      principal_id = "00000000-0000-0000-0000-000000000004"
      client_id    = "00000000-0000-0000-0000-000000000005"
    }
  }
}

mock_provider "azapi" {}

run "dev_plan" {
  command = plan
  variables {
    env = "dev"
  }
  assert {
    condition     = azurerm_cognitive_account.foundry.local_auth_enabled == false
    error_message = "Microsoft Foundry resource must not accept API keys"
  }
  assert {
    condition     = azurerm_container_app.api.template[0].min_replicas == 0
    error_message = "API must scale to zero when idle"
  }
  assert {
    condition     = azurerm_cognitive_deployment.chat.sku[0].capacity <= 50
    error_message = "model capacity must stay small"
  }
  assert {
    condition     = azurerm_key_vault.kv.rbac_authorization_enabled && azurerm_key_vault.kv.purge_protection_enabled
    error_message = "Key Vault must use RBAC and purge protection"
  }
  assert {
    condition     = azapi_resource.auth.body.properties.globalValidation.unauthenticatedClientAction == "Return401"
    error_message = "API must reject unauthenticated callers"
  }
}

run "bad_env_rejected" {
  command = plan
  variables {
    env = "staging"
  }
  expect_failures = [var.env]
}

run "capacity_cap" {
  command = plan
  variables {
    env            = "dev"
    model_capacity = 500
  }
  expect_failures = [var.model_capacity]
}
