terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
  required_version = ">= 1.3.0"

  backend "s3" {
    # Backend configuration is provided via backend.tfvars or command line
    # Example: terraform init -backend-config="bucket=my-terraform-state"
    # Or use backend.tfvars file
  }
}

provider "aws" {
  region = var.aws_region
}
