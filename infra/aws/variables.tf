variable "region" {
  description = "AWS region; keep the data in the tenant's allowed region (see governance layer)."
  type        = string
  default     = "eu-west-2"
}

variable "name" {
  description = "Name prefix for every resource."
  type        = string
  default     = "harrowgate-assist"
}

variable "image_tag" {
  description = "Immutable image tag (git SHA) pushed to the repository."
  type        = string
  default     = "replace-with-git-sha"
}

variable "model_id" {
  description = "Managed model the task role may call (Bedrock model id)."
  type        = string
  default     = "replace-with-approved-model-id"
}

variable "private_subnet_ids" {
  description = "Private subnets for the service (no public IPs)."
  type        = list(string)
  default     = []
}

variable "vpc_id" {
  description = "VPC for the service security group."
  type        = string
  default     = "vpc-00000000"
}
