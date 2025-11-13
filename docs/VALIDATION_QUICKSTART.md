# Quick Validation Guide

## Quick Validation Steps

### 1. Pre-Deployment Checks

```bash
# Validate Terraform configuration
terraform validate

# Check format
terraform fmt -check

# Initialize (if not done)
terraform init -backend-config=backend.tfvars
```

### 2. Post-Deployment Validation

```bash
# Run automated validation script
./scripts/validate.sh

# Or manually check key resources:

# Get all outputs
terraform output

# Verify S3 bucket
aws s3 ls s3://$(terraform output -raw s3_bucket)

# Verify Lambda functions exist
aws lambda list-functions --query "Functions[?starts_with(FunctionName, 'bedrock-ci-agent')].FunctionName"

# Verify Bedrock agents exist
aws bedrock-agent list-agents --query "agentSummaries[?starts_with(agentName, 'bedrock-ci-agent')]"
```

### 3. Test Lambda Functions

```bash
# Test Repository Ingestor
aws lambda invoke \
  --function-name $(terraform output -raw lambda_repo_ingestor) \
  --cli-binary-format raw-in-base64-out \
  --payload '{"repo_url": "https://github.com/octocat/Hello-World", "branch": "main"}' \
  response.json && cat response.json

# Test Template Validator
aws lambda invoke \
  --function-name $(terraform output -raw lambda_template_validator) \
  --cli-binary-format raw-in-base64-out \
  --payload '{"yaml_content": "name: Test\non: [push]\njobs:\n  test:\n    runs-on: ubuntu-latest"}' \
  response.json && cat response.json
```

### 4. Test Bedrock Agent

```bash
AGENT_ID=$(terraform output -raw bedrock_agent_repo_scanner_id)

aws bedrock-agent-runtime invoke-agent \
  --agent-id $AGENT_ID \
  --agent-alias-id TSTALIASID \
  --session-id "test-$(date +%s)" \
  --input-text "Analyze repository: https://github.com/octocat/Hello-World" \
  response.json && cat response.json
```

### 5. End-to-End Test

```bash
# Invoke orchestrator with test repository
aws lambda invoke \
  --function-name $(terraform output -raw lambda_orchestrator) \
  --cli-binary-format raw-in-base64-out \
  --payload "{
    \"task_id\": \"test-$(date +%s)\",
    \"repo_url\": \"https://github.com/YOUR_ORG/YOUR_REPO\",
    \"branch\": \"main\",
    \"agent_ids\": $(terraform output -json agent_ids_map)
  }" \
  response.json && cat response.json
```

## Common Issues

### Bedrock Agent Not Responding
- Verify agent is prepared: `aws bedrock-agent prepare-agent --agent-id <ID>`
- Check agent alias exists
- Verify IAM permissions

### Lambda Function Errors
- Check CloudWatch logs: `aws logs tail /aws/lambda/<function-name> --follow`
- Verify environment variables are set
- Check IAM permissions

### "Invalid base64" Error
- Add `--cli-binary-format raw-in-base64-out` flag to `aws lambda invoke` commands
- Required for AWS CLI v2 when passing JSON payloads

### GitHub API Fails
- Update GitHub PAT in Secrets Manager
- Verify PAT has `repo` scope permissions
- Check repository exists and is accessible

## Full Documentation

For comprehensive validation steps, see [VALIDATION.md](./VALIDATION.md)

