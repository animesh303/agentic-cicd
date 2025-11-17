# S3 Backend Configuration
# This file can be used to configure the backend programmatically
# Alternatively, use backend.tfvars or command-line flags

# Uncomment and configure if you want to use variables for backend config
# Note: Backend configuration cannot use variables directly, so this is a template
# Use backend.tfvars or command-line flags instead

terraform {
  backend "s3" {
    bucket         = "bedrock-ci-agent-terraform-state-027378719919"
    key            = "bedrock-ci-agent/terraform.tfstate"
    region         = "us-east-1"
    encrypt        = true
    dynamodb_table = "terraform-state-lock"
  }
}

