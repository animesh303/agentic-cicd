# Amazon Bedrock Agentic CI/CD Generator (Terraform)

This Terraform project deploys an Amazon Bedrock Agent plus supporting infra to implement an AI agentic workflow that:

- Scans a GitHub repo (via Lambda)
- Designs a CI/CD pipeline
- Generates GitHub Actions YAML
- Opens a PR in the repo with the workflow

**What you get**

- S3 bucket for templates and OpenAPI docs
- Lambda function `repo_scanner` (Python)
- IAM Roles and Policies
- Secrets Manager secret for `GITHUB_PAT`
- Bedrock Agent + Prompt resources wired to the Lambda and OpenAPI action groups (skeleton)

**Prerequisites**

- Terraform v1.5+ (recommended)
- AWS CLI configured with an account that has Bedrock access
- Bedrock service enabled in your AWS account
- A GitHub PAT with `repo` permissions (store in `terraform.tfvars` or Secrets Manager after deploy)

**Quick start**

1. **Set up S3 backend** (see `docs/BACKEND_SETUP.md` for details):
   - Create S3 bucket for state storage
   - Optionally create DynamoDB table for state locking
   - Copy `backend.tfvars.example` to `backend.tfvars` and configure
2. Edit `terraform.tfvars` with your values.
3. Initialize Terraform with backend:
   ```bash
   terraform init -backend-config=backend.tfvars
   ```
4. `terraform apply -auto-approve`
5. After apply, the agent may need a short initialization period. The Terraform output shows agent IDs.
6. **Validate the deployment:**

   ```bash
   # Run automated validation script
   ./scripts/validate.sh

   # Or follow the comprehensive validation guide
   # See docs/VALIDATION.md for detailed validation steps
   ```

**Notes & next steps**

- Review IAM policies — this config gives the agent permissions to invoke Lambda and manage knowledge bases; tighten for production.
- The Bedrock Terraform resources are evolving. If a resource fails, consult the Terraform AWS provider docs or the AWS Bedrock docs.
- **Update GitHub PAT** in Secrets Manager after deployment (currently has placeholder value)
- See `docs/VALIDATION.md` for comprehensive validation guide
