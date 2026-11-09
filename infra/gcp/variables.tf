variable "project" {
  description = "Google Cloud project id."
  type        = string
  default     = "replace-with-project-id"
}

variable "region" {
  description = "Region; keep data in the tenant's allowed region."
  type        = string
  default     = "europe-west2"
}

variable "name" {
  description = "Name prefix."
  type        = string
  default     = "harrowgate-assist"
}

variable "image_tag" {
  description = "Immutable image tag (git SHA)."
  type        = string
  default     = "replace-with-git-sha"
}

variable "model_id" {
  description = "Managed model id on Vertex AI."
  type        = string
  default     = "replace-with-approved-model-id"
}
