variable "aws_region" {
  type    = string
  default = "us-east-1"
}

variable "project_prefix" {
  type    = string
  default = "bedrock-ci-agent"
}

variable "bucket_name" {
  type = string
}

variable "github_pat_secret_name" {
  type = string
}

variable "lambda_s3_key" {
  type = string
}

variable "lambda_handler" {
  type = string
}

variable "lambda_runtime" {
  type = string
}

variable "bedrock_foundation_model" {
  type        = string
  description = "Bedrock inference profile identifier for agents (e.g., us.anthropic.claude-3-5-sonnet-20241022-v2:0). Use inference profile ID, not direct model ID."
  default     = "us.anthropic.claude-3-5-sonnet-20241022-v2:0"
}

variable "agent_alias_id" {
  type        = string
  description = "Bedrock agent alias ID (default: TSTALIASID for draft agents)"
  default     = "TSTALIASID"
}

variable "terraform_state_bucket" {
  type        = string
  description = "S3 bucket name for Terraform state storage"
  default     = ""
}

variable "terraform_state_key" {
  type        = string
  description = "S3 key/path for Terraform state file"
  default     = "terraform.tfstate"
}

variable "terraform_state_region" {
  type        = string
  description = "AWS region for Terraform state bucket"
  default     = ""
}

variable "terraform_state_dynamodb_table" {
  type        = string
  description = "DynamoDB table name for Terraform state locking (optional)"
  default     = ""
}

variable "terraform_state_encrypt" {
  type        = bool
  description = "Enable encryption for Terraform state"
  default     = true
}
