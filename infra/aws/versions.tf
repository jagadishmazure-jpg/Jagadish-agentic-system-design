# AWS option. WRITTEN, NOT RUN: validated in CI, never applied. Nothing here is billable until someone
# runs `terraform apply` with real credentials, which no workflow in this repository does.
terraform {
  required_version = ">= 1.9.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}

provider "aws" {
  region = var.region
}
