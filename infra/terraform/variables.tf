variable "env" {
  description = "Environment name (dev or prod)."
  type        = string
  validation {
    condition     = contains(["dev", "prod"], var.env)
    error_message = "env must be dev or prod."
  }
}

variable "location" {
  description = "Azure region."
  type        = string
  default     = "eastus2"
}

variable "prefix" {
  description = "Short lowercase name prefix (3-10 letters or digits)."
  type        = string
  default     = "hgasd"
  validation {
    condition     = can(regex("^[a-z0-9]{3,10}$", var.prefix))
    error_message = "prefix must be 3-10 lowercase letters or digits."
  }
}

variable "container_image" {
  description = "Container image for the assistant API (built from the repo Dockerfile)."
  type        = string
  default     = "ghcr.io/jagadishmazure-jpg/harrowgate-assistant:0.1.0"
}

variable "model_name" {
  description = "Chat model deployed in Microsoft Foundry for request understanding."
  type        = string
  default     = "gpt-4o-mini"
}

variable "model_version" {
  description = "Model version."
  type        = string
  default     = "2024-07-18"
}

variable "model_capacity" {
  description = "Deployment capacity in thousands of tokens per minute (kept small on purpose)."
  type        = number
  default     = 10
  validation {
    condition     = var.model_capacity >= 1 && var.model_capacity <= 50
    error_message = "model_capacity must be 1-50 for this demo stack."
  }
}

variable "max_replicas" {
  description = "Upper bound on API replicas (scale to zero when idle)."
  type        = number
  default     = 2
}

variable "log_retention_days" {
  description = "Log Analytics retention."
  type        = number
  default     = 30
}

variable "tags" {
  description = "Tags on every resource."
  type        = map(string)
  default = {
    workload = "harrowgate-assistant"
    owner    = "airport-digital"
    data     = "synthetic"
  }
}

variable "api_client_id" {
  description = "Entra ID app registration (client id) that callers authenticate against."
  type        = string
  default     = "00000000-0000-0000-0000-000000000000"
}
