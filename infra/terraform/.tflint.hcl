plugin "terraform" {
  enabled = true
  preset  = "recommended"
}

plugin "azurerm" {
  enabled = true
  version = "0.32.0"
  source  = "github.com/terraform-linters/tflint-ruleset-azurerm"
}

# Written-not-run demo stack: it would be created and torn down by the gated deploy workflow and holds
# only synthetic data, so prevent_destroy would only block teardown.
rule "azurerm_resources_missing_prevent_destroy" {
  enabled = false
}
