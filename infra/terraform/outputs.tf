output "resource_group" {
  description = "Resource group name."
  value       = azurerm_resource_group.rg.name
}

output "api_fqdn" {
  description = "Public host name of the assistant API (Entra ID sign-in required)."
  value       = azurerm_container_app.api.ingress[0].fqdn
}

output "foundry_endpoint" {
  description = "Microsoft Foundry endpoint used by the app's managed identity."
  value       = azurerm_cognitive_account.foundry.endpoint
}
