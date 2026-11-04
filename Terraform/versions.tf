terraform {
  required_version = ">= 1.10.0, < 2.0.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 6.0, < 7.0"
    }
  }
}

provider "aws" {
  region              = var.aws_region
  allowed_account_ids = [var.target_account_id]
  default_tags {
    tags = { Project = var.name, ManagedBy = "Terraform", Environment = "sandbox" }
  }
}
