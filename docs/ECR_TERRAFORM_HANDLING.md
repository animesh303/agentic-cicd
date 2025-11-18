# ECR Resources from Terraform - CI/CD Workflow Handling

## Overview

When ECR repositories are created by Terraform Infrastructure as Code (IaC), the CI/CD workflow needs to:

1. **Deploy infrastructure FIRST** - ECR resources must exist before container build
2. **Dynamically retrieve ECR information** - Get registry and repository from Terraform outputs
3. **Proper job sequencing** - Infrastructure job must run before container build job
4. **Terraform setup order** - Setup Terraform CLI before any terraform commands

## Solution Architecture

### 1. Detection Phase (Static Analyzer)

The `static_analyzer.py` Lambda function now includes `analyze_terraform_ecr()` which:

- Scans all `.tf` files in the repository
- Detects `aws_ecr_repository` resources
- Identifies Terraform outputs related to ECR
- Returns structured data about ECR resources and outputs

**Detection Patterns:**

- ECR Resources: `resource "aws_ecr_repository" "name" { ... }`
- ECR Outputs: `output "ecr_registry" { ... }` or `output "ecr_repository" { ... }`
- Account ID Detection: `data "aws_caller_identity" "current" {}`

### 2. Workflow Generation Phase (YAML Generator)

The orchestrator passes ECR guidance to the YAML generator agent based on Terraform analysis:

**If ECR is detected in Terraform:**

- Instructs agent to use Terraform outputs
- Provides pattern for extracting ECR values
- Guides on constructing registry URL from account ID and region

**If ECR is not in Terraform:**

- Falls back to GitHub variables (`vars.ECR_REGISTRY`, `vars.ECR_REPOSITORY`)
- Provides guidance for both scenarios

## Terraform Configuration Best Practices

### Recommended: Add ECR Outputs

```hcl
# Create ECR repository
resource "aws_ecr_repository" "app" {
  name                 = "my-app"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }
}

# Get AWS account ID
data "aws_caller_identity" "current" {}

# Output ECR registry
output "ecr_registry" {
  description = "ECR registry URL"
  value       = "${data.aws_caller_identity.current.account_id}.dkr.ecr.${var.aws_region}.amazonaws.com"
}

# Output ECR repository name
output "ecr_repository" {
  description = "ECR repository name"
  value       = aws_ecr_repository.app.name
}

# Output full repository URL (optional)
output "ecr_repository_url" {
  description = "Full ECR repository URL"
  value       = aws_ecr_repository.app.repository_url
}
```

### Alternative: Use Resource References

If outputs are not defined, the workflow can still extract values:

```hcl
# The workflow will detect the resource and extract:
# - Repository name from resource attribute
# - Registry from account ID + region
```

## Generated Workflow Patterns

### Pattern 1: Using Terraform Outputs (Recommended)

**CRITICAL:** Infrastructure job MUST run BEFORE container build job when ECR is created by Terraform.

```yaml
jobs:
  # Quality and security checks first
  quality:
    runs-on: ubuntu-latest
    steps: [...]

  security:
    runs-on: ubuntu-latest
    needs: [quality]
    steps: [...]

  # Infrastructure deployment (MUST run before container build)
  infrastructure:
    runs-on: ubuntu-latest
    needs: [quality, security]
    steps:
      - uses: actions/checkout@v4

      - name: Configure AWS Credentials
        uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: ${{ secrets.AWS_ROLE_TO_ASSUME }}
          aws-region: ${{ vars.AWS_REGION }}

      # CRITICAL: Setup Terraform BEFORE any terraform commands
      - name: Setup Terraform
        uses: hashicorp/setup-terraform@v3
        with:
          cli_config_credentials_token: ${{ secrets.TF_API_TOKEN }}

      - name: Terraform Init
        run: terraform init

      - name: Terraform Plan
        run: terraform plan

      - name: Terraform Apply
        run: terraform apply -auto-approve

      - name: Get ECR Outputs
        id: ecr-outputs
        run: |
          terraform output -json > terraform_outputs.json
          ECR_REGISTRY=$(jq -r '.ecr_registry.value' terraform_outputs.json)
          ECR_REPOSITORY=$(jq -r '.ecr_repository.value' terraform_outputs.json)
          echo "ECR_REGISTRY=$ECR_REGISTRY" >> $GITHUB_ENV
          echo "ECR_REPOSITORY=$ECR_REPOSITORY" >> $GITHUB_ENV

  # Container build (depends on infrastructure)
  container:
    runs-on: ubuntu-latest
    needs: [infrastructure] # CRITICAL: Must wait for infrastructure
    steps:
      - uses: actions/checkout@v4

      - name: Configure AWS Credentials
        uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: ${{ secrets.AWS_ROLE_TO_ASSUME }}
          aws-region: ${{ vars.AWS_REGION }}

      - name: Get Terraform Outputs
        run: |
          terraform init
          terraform output -json > terraform_outputs.json
          ECR_REGISTRY=$(jq -r '.ecr_registry.value' terraform_outputs.json)
          ECR_REPOSITORY=$(jq -r '.ecr_repository.value' terraform_outputs.json)
          echo "ECR_REGISTRY=$ECR_REGISTRY" >> $GITHUB_ENV
          echo "ECR_REPOSITORY=$ECR_REPOSITORY" >> $GITHUB_ENV

      - name: Login to Amazon ECR
        uses: aws-actions/amazon-ecr-login@v2

      - name: Build and Push Container
        run: |
          docker build -t $ECR_REGISTRY/$ECR_REPOSITORY:${{ github.sha }} .
          docker push $ECR_REGISTRY/$ECR_REPOSITORY:${{ github.sha }}
```

### Pattern 2: Deriving from Account ID (Fallback)

**Note:** Still requires infrastructure job to run first to create ECR repository.

```yaml
jobs:
  infrastructure:
    runs-on: ubuntu-latest
    needs: [quality, security]
    steps:
      - name: Setup Terraform
        uses: hashicorp/setup-terraform@v3
        with:
          cli_config_credentials_token: ${{ secrets.TF_API_TOKEN }}
      - name: Terraform Init
        run: terraform init
      - name: Terraform Apply
        run: terraform apply -auto-approve

  container:
    runs-on: ubuntu-latest
    needs: [infrastructure] # Must wait for ECR to be created
    steps:
      - name: Get AWS Account ID
        id: aws-account
        run: |
          ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
          ECR_REGISTRY="$ACCOUNT_ID.dkr.ecr.${{ vars.AWS_REGION }}.amazonaws.com"
          echo "ECR_REGISTRY=$ECR_REGISTRY" >> $GITHUB_ENV
          # Extract repository name from Terraform resource if needed
```

### Pattern 3: Using GitHub Variables (Pre-configured)

```yaml
- name: Build and Push Container
  env:
    ECR_REGISTRY: ${{ vars.ECR_REGISTRY }}
    ECR_REPOSITORY: ${{ vars.ECR_REPOSITORY }}
  run: |
    docker build -t $ECR_REGISTRY/$ECR_REPOSITORY:${{ github.sha }} .
    docker push $ECR_REGISTRY/$ECR_REPOSITORY:${{ github.sha }}
```

## Implementation Details

### Static Analyzer Enhancement

**File:** `lambda/static_analyzer.py`

**Function:** `analyze_terraform_ecr(tmpdir)`

**Returns:**

```python
{
    'ecr_resources': [
        {
            'resource_name': 'app',
            'repository_name': 'my-app',
            'file': 'main.tf'
        }
    ],
    'ecr_outputs': [
        {
            'output_name': 'ecr_registry',
            'output_value': '...',
            'value_reference': 'aws_ecr_repository.app.repository_url',
            'file': 'outputs.tf'
        }
    ],
    'has_ecr': True
}
```

### Orchestrator Logic

**File:** `lambda/orchestrator.py`

**Location:** YAML Generator Agent prompt construction

**Logic:**

1. Check if `terraform_analysis` exists in static analyzer results
2. If `has_ecr` is True, provide Terraform-specific guidance
3. Otherwise, provide variable-based guidance with fallback option

### YAML Generator Prompt

**File:** `lambda/agent_prompts/yaml_generator_base.txt`

**Enhancement:** Added `{ecr_guidance}` placeholder that gets populated with scenario-specific instructions.

## Testing

### Test Case 1: ECR in Terraform with Outputs

1. Create Terraform with ECR resource and outputs
2. Run orchestrator
3. Verify generated workflow uses `terraform output -json`
4. Verify ECR values extracted from outputs

### Test Case 2: ECR in Terraform without Outputs

1. Create Terraform with ECR resource but no outputs
2. Run orchestrator
3. Verify generated workflow derives registry from account ID
4. Verify repository name extracted from resource

### Test Case 3: ECR Not in Terraform

1. Repository without Terraform ECR resources
2. Run orchestrator
3. Verify generated workflow uses GitHub variables
4. Verify fallback guidance provided

## Migration Guide

### From Variables to Terraform Outputs

1. **Add Terraform outputs** (see recommended configuration above)
2. **Update workflow** to use Terraform outputs instead of variables
3. **Remove GitHub variables** `ECR_REGISTRY` and `ECR_REPOSITORY` (optional)
4. **Test workflow** to ensure ECR values are correctly extracted

### Benefits

- **Single Source of Truth:** ECR configuration in Terraform
- **No Manual Configuration:** No need to set GitHub variables
- **Consistency:** Same values used in infrastructure and CI/CD
- **Automation:** Workflow automatically adapts to Terraform changes

## Troubleshooting

### Issue: Workflow can't find Terraform outputs

**Solution:**

- Ensure Terraform outputs are defined
- Ensure infrastructure job runs before container job
- Ensure workflow runs `terraform init` before `terraform output`
- Verify Terraform setup step comes before terraform init

### Issue: ECR registry URL incorrect

**Solution:** Verify AWS account ID and region are correct. Use `aws sts get-caller-identity` to verify account ID.

### Issue: Repository name not found

**Solution:** Check that `aws_ecr_repository` resource has a `name` attribute, or use `repository_url` output if available.

### Issue: Container build fails because ECR doesn't exist

**Solution:**

- Verify infrastructure job runs before container job
- Check job dependencies: `needs: [infrastructure]` in container job
- Ensure terraform apply completed successfully in infrastructure job
- Verify ECR repository was actually created by checking Terraform state

### Issue: Terraform commands fail

**Solution:**

- Ensure Terraform setup step (hashicorp/setup-terraform@v3) runs BEFORE terraform init
- Verify cli_config_credentials_token is set if using Terraform Cloud/Enterprise
- Check that Terraform setup step is the first step after checkout and AWS credentials

## Future Enhancements

1. **Support for multiple ECR repositories** - Detect and handle multiple ECR resources
2. **ECR lifecycle policies** - Detect and reference lifecycle policies
3. **Cross-account ECR** - Support for ECR repositories in different AWS accounts
4. **ECR replication** - Handle replicated repositories
