# Harrowgate passenger assistant on Azure. WRITTEN, NOT RUN.
# Creates: resource group, Log Analytics, Application Insights, a user-assigned identity, Key Vault (RBAC),
# a Microsoft Foundry resource (AIServices) with one small chat deployment and local (key) auth disabled,
# and a Container Apps environment + app that scales to zero. The app reaches the model with its managed
# identity; there are no API keys anywhere. Deployment is gated off in .github/workflows/deploy.yml.

data "azurerm_client_config" "current" {}

locals {
  name = "${var.prefix}-${var.env}"
}

resource "azurerm_resource_group" "rg" {
  name     = "rg-${local.name}"
  location = var.location
  tags     = var.tags
}

resource "azurerm_log_analytics_workspace" "logs" {
  name                = "log-${local.name}"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  sku                 = "PerGB2018"
  retention_in_days   = var.log_retention_days
  tags                = var.tags
}

resource "azurerm_application_insights" "appi" {
  name                = "appi-${local.name}"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  workspace_id        = azurerm_log_analytics_workspace.logs.id
  application_type    = "other"
  tags                = var.tags
}

resource "azurerm_user_assigned_identity" "app" {
  name                = "id-${local.name}"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  tags                = var.tags
}

# Holds the trace-pseudonym key and the policy signing key (values are set out of band, never in IaC).
resource "azurerm_key_vault" "kv" {
  name                       = "kv-${local.name}"
  location                   = azurerm_resource_group.rg.location
  resource_group_name        = azurerm_resource_group.rg.name
  tenant_id                  = data.azurerm_client_config.current.tenant_id
  sku_name                   = "standard"
  rbac_authorization_enabled = true
  purge_protection_enabled   = true
  soft_delete_retention_days = 7
  tags                       = var.tags

  network_acls {
    bypass         = "AzureServices"
    default_action = "Allow"
  }
}

# Microsoft Foundry resource: keys disabled, Entra ID only.
resource "azurerm_cognitive_account" "foundry" {
  name                  = "aif-${local.name}"
  location              = azurerm_resource_group.rg.location
  resource_group_name   = azurerm_resource_group.rg.name
  kind                  = "AIServices"
  sku_name              = "S0"
  custom_subdomain_name = "aif-${local.name}"
  local_auth_enabled    = false
  tags                  = var.tags

  identity {
    type = "SystemAssigned"
  }

  network_acls {
    default_action = "Allow"
  }
}

resource "azurerm_cognitive_deployment" "chat" {
  name                 = "chat"
  cognitive_account_id = azurerm_cognitive_account.foundry.id

  model {
    format  = "OpenAI"
    name    = var.model_name
    version = var.model_version
  }

  sku {
    name     = "GlobalStandard"
    capacity = var.model_capacity
  }
}

resource "azurerm_role_assignment" "app_model" {
  scope                = azurerm_cognitive_account.foundry.id
  role_definition_name = "Cognitive Services OpenAI User"
  principal_id         = azurerm_user_assigned_identity.app.principal_id
}

resource "azurerm_role_assignment" "app_secrets" {
  scope                = azurerm_key_vault.kv.id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_user_assigned_identity.app.principal_id
}

resource "azurerm_container_app_environment" "env" {
  name                       = "cae-${local.name}"
  location                   = azurerm_resource_group.rg.location
  resource_group_name        = azurerm_resource_group.rg.name
  log_analytics_workspace_id = azurerm_log_analytics_workspace.logs.id
  tags                       = var.tags
}

resource "azurerm_container_app" "api" {
  name                         = "ca-${local.name}"
  container_app_environment_id = azurerm_container_app_environment.env.id
  resource_group_name          = azurerm_resource_group.rg.name
  revision_mode                = "Single"
  tags                         = var.tags

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.app.id]
  }

  ingress {
    external_enabled = true
    target_port      = 8080
    transport        = "auto"
    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }

  template {
    min_replicas = 0
    max_replicas = var.max_replicas

    container {
      name   = "api"
      image  = var.container_image
      cpu    = 0.25
      memory = "0.5Gi"

      env {
        name  = "HARROWGATE_LLM"
        value = "mock"
      }
      env {
        name  = "FOUNDRY_ENDPOINT"
        value = azurerm_cognitive_account.foundry.endpoint
      }
      env {
        name  = "FOUNDRY_DEPLOYMENT"
        value = azurerm_cognitive_deployment.chat.name
      }
      env {
        name  = "AZURE_CLIENT_ID"
        value = azurerm_user_assigned_identity.app.client_id
      }
      env {
        name  = "APPLICATIONINSIGHTS_CONNECTION_STRING"
        value = azurerm_application_insights.appi.connection_string
      }

      liveness_probe {
        transport = "HTTP"
        port      = 8080
        path      = "/healthz"
      }
    }
  }
}

# Only signed-in Entra ID callers reach the API (Container Apps built-in authentication).
resource "azapi_resource" "auth" {
  type      = "Microsoft.App/containerApps/authConfigs@2024-03-01"
  name      = "current"
  parent_id = azurerm_container_app.api.id

  body = {
    properties = {
      platform         = { enabled = true }
      globalValidation = { unauthenticatedClientAction = "Return401" }
      identityProviders = {
        azureActiveDirectory = {
          enabled = true
          registration = {
            clientId     = var.api_client_id
            openIdIssuer = "https://login.microsoftonline.com/${data.azurerm_client_config.current.tenant_id}/v2.0"
          }
        }
      }
    }
  }
}

resource "azurerm_monitor_diagnostic_setting" "foundry" {
  name                       = "diag-foundry"
  target_resource_id         = azurerm_cognitive_account.foundry.id
  log_analytics_workspace_id = azurerm_log_analytics_workspace.logs.id

  enabled_log {
    category_group = "allLogs"
  }
}

resource "azurerm_monitor_diagnostic_setting" "kv" {
  name                       = "diag-kv"
  target_resource_id         = azurerm_key_vault.kv.id
  log_analytics_workspace_id = azurerm_log_analytics_workspace.logs.id

  enabled_log {
    category = "AuditEvent"
  }
}
