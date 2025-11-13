# Solution Validation Guide

This guide provides comprehensive steps to validate the Agentic CI/CD solution after deployment.

## Table of Contents

1. [Pre-Deployment Validation](#pre-deployment-validation)
2. [Post-Deployment Validation](#post-deployment-validation)
3. [Lambda Function Validation](#lambda-function-validation)
4. [Bedrock Agent Validation](#bedrock-agent-validation)
5. [End-to-End Workflow Validation](#end-to-end-workflow-validation)
6. [Security Validation](#security-validation)
7. [Monitoring & Observability Validation](#monitoring--observability-validation)

---

## Pre-Deployment Validation

### 1. Terraform Configuration Validation

```bash
# Validate Terraform syntax
terraform validate

# Format check
terraform fmt -check

# Initialize with backend
terraform init -backend-config=backend.tfvars

# Review planned changes
terraform plan -out=tfplan
```

**Expected Results:**

- ✅ No syntax errors
- ✅ All variables are defined
- ✅ Backend configuration is valid
- ✅ Plan shows expected resources (6 Lambda functions, 6 Bedrock agents, S3 bucket, DynamoDB table, etc.)

### 2. Variable Validation

Check that `terraform.tfvars` contains:

- ✅ `bucket_name` - Globally unique S3 bucket name
- ✅ `github_pat_secret_name` - Secrets Manager secret name
- ✅ `aws_region` - Valid AWS region with Bedrock access
- ✅ Other variables have appropriate defaults

### 3. Prerequisites Check

```bash
# Check AWS CLI configuration
aws sts get-caller-identity

# Check Bedrock access
aws bedrock list-foundation-models --region us-east-1

# Check Terraform version (should be 1.5+)
terraform version
```

---

## Post-Deployment Validation

### 1. Infrastructure Resources Check

After `terraform apply`, verify all resources exist:

```bash
# Get outputs
terraform output

# Verify S3 bucket exists
aws s3 ls s3://$(terraform output -raw s3_bucket)

# Verify DynamoDB table exists
aws dynamodb describe-table --table-name $(terraform output -raw dynamodb_table)

# Verify Lambda functions exist
aws lambda list-functions --query "Functions[?starts_with(FunctionName, 'bedrock-ci-agent')].FunctionName"
```

**Expected Results:**

- ✅ S3 bucket exists and contains OpenAPI specs
- ✅ DynamoDB table exists
- ✅ 6 Lambda functions exist:
  - `bedrock-ci-agent-repo-scanner`
  - `bedrock-ci-agent-repo-ingestor`
  - `bedrock-ci-agent-static-analyzer`
  - `bedrock-ci-agent-template-validator`
  - `bedrock-ci-agent-orchestrator`
  - `bedrock-ci-agent-github-api`

### 2. Bedrock Agents Check

```bash
# List all agents
aws bedrock-agent list-agents --query "agentSummaries[?starts_with(agentName, 'bedrock-ci-agent')]"

# Get agent details (replace with actual agent ID from outputs)
AGENT_ID=$(terraform output -raw bedrock_agent_repo_scanner_id)
aws bedrock-agent get-agent --agent-id $AGENT_ID

# Check agent aliases
aws bedrock-agent list-agent-aliases --agent-id $AGENT_ID
```

**Expected Results:**

- ✅ 6 Bedrock agents exist:
  - Repo Scanner Agent
  - Pipeline Designer Agent
  - Security & Compliance Agent
  - YAML Generator Agent
  - PR Manager Agent
  - Feedback Agent
- ✅ Each agent has DRAFT version
- ✅ Each agent has TSTALIASID alias

### 3. IAM Roles and Policies

```bash
# Check Lambda execution role
aws iam get-role --role-name bedrock-ci-agent-lambda-exec

# Check Bedrock agent role
aws iam get-role --role-name bedrock-ci-agent-bedrock-agent-role

# Verify policies are attached
aws iam list-attached-role-policies --role-name bedrock-ci-agent-lambda-exec
aws iam list-attached-role-policies --role-name bedrock-ci-agent-bedrock-agent-role
```

**Expected Results:**

- ✅ Lambda execution role exists with proper policies
- ✅ Bedrock agent role exists with Lambda invoke permissions
- ✅ Policies allow S3, Secrets Manager, DynamoDB, Bedrock access

### 4. Secrets Manager

```bash
# Check GitHub PAT secret exists
SECRET_NAME=$(terraform output -raw github_pat_secret_name 2>/dev/null || echo "bedrock/github/pat")
aws secretsmanager describe-secret --secret-id $SECRET_NAME

# Note: Secret value should be updated after deployment
```

**Expected Results:**

- ✅ Secret exists
- ⚠️ Secret value should be updated from placeholder

---

## Lambda Function Validation

### 1. Test Individual Lambda Functions

#### Repository Ingestor

```bash
LAMBDA_NAME=$(terraform output -raw lambda_repo_ingestor)

aws lambda invoke \
  --function-name $LAMBDA_NAME \
  --cli-binary-format raw-in-base64-out \
  --payload '{"repo_url": "https://github.com/octocat/Hello-World", "branch": "main"}' \
  response.json

cat response.json
```

**Expected Results:**

- ✅ Lambda executes successfully
- ✅ Returns structured JSON with repository contents
- ✅ Contains Dockerfiles, manifests, IaC files if present

#### Static Analyzer

```bash
LAMBDA_NAME=$(terraform output -raw lambda_static_analyzer)

# Test with sample Dockerfile content
aws lambda invoke \
  --function-name $LAMBDA_NAME \
  --cli-binary-format raw-in-base64-out \
  --payload '{
    "dockerfile_content": "FROM node:14\nRUN npm install",
    "manifest_files": {"package.json": "{\"dependencies\": {}}"}
  }' \
  response.json

cat response.json
```

**Expected Results:**

- ✅ Analyzes Dockerfile for security issues
- ✅ Detects dependencies
- ✅ Identifies test frameworks

#### Template Validator

```bash
LAMBDA_NAME=$(terraform output -raw lambda_template_validator)

# Test with sample GitHub Actions YAML
aws lambda invoke \
  --function-name $LAMBDA_NAME \
  --cli-binary-format raw-in-base64-out \
  --payload '{
    "yaml_content": "name: Test\non: [push]\njobs:\n  test:\n    runs-on: ubuntu-latest",
    "validation_level": "normal"
  }' \
  response.json

cat response.json
```

**Expected Results:**

- ✅ Validates YAML syntax
- ✅ Checks GitHub Actions structure
- ✅ Validates secrets usage
- ✅ Returns validation results

#### GitHub API Lambda

```bash
LAMBDA_NAME=$(terraform output -raw lambda_github_api)

# Test with sample PR creation request
aws lambda invoke \
  --function-name $LAMBDA_NAME \
  --cli-binary-format raw-in-base64-out \
  --payload '{
    "operation": "create_pr",
    "owner": "test-owner",
    "repo": "test-repo",
    "title": "Test PR",
    "head": "feature-branch",
    "base": "main",
    "body": "Test PR description"
  }' \
  response.json

cat response.json
```

**Expected Results:**

- ✅ Handles GitHub API operations
- ✅ Uses GitHub PAT from Secrets Manager
- ⚠️ May fail if PAT is not configured or repo doesn't exist (expected)

### 2. Check Lambda Logs

```bash
# Check CloudWatch logs for errors
aws logs tail /aws/lambda/$(terraform output -raw lambda_orchestrator) --follow

# Check for recent errors
aws logs filter-log-events \
  --log-group-name /aws/lambda/$(terraform output -raw lambda_orchestrator) \
  --filter-pattern "ERROR" \
  --max-items 10
```

---

## Bedrock Agent Validation

### 1. Test Repo Scanner Agent

```bash
AGENT_ID=$(terraform output -raw bedrock_agent_repo_scanner_id)
ALIAS_ID="TSTALIASID"
SESSION_ID="test-session-$(date +%s)"

aws bedrock-agent-runtime invoke-agent \
  --agent-id $AGENT_ID \
  --agent-alias-id $ALIAS_ID \
  --session-id $SESSION_ID \
  --input-text "Analyze repository: https://github.com/octocat/Hello-World" \
  --endpoint-url "https://bedrock-agent-runtime.us-east-1.amazonaws.com" \
  --region us-east-1 \
  response.json

cat response.json
```

**Expected Results:**

- ✅ Agent responds
- ✅ Agent invokes Repository Ingestor Lambda via action group
- ✅ Returns repository analysis

### 2. Test Pipeline Designer Agent

```bash
AGENT_ID=$(terraform output -raw bedrock_agent_pipeline_designer_id)
SESSION_ID="test-session-$(date +%s)"

aws bedrock-agent-runtime invoke-agent \
  --agent-id $AGENT_ID \
  --agent-alias-id $ALIAS_ID \
  --session-id $SESSION_ID \
  --input-text "Design a CI/CD pipeline for a Python application with Docker, tests, and ECS deployment" \
  response.json

cat response.json
```

**Expected Results:**

- ✅ Agent provides pipeline design
- ✅ Includes build, test, scan, deploy stages
- ✅ Considers security and best practices

### 3. Test YAML Generator Agent

```bash
AGENT_ID=$(terraform output -raw bedrock_agent_yaml_generator_id)
SESSION_ID="test-session-$(date +%s)"

aws bedrock-agent-runtime invoke-agent \
  --agent-id $AGENT_ID \
  --agent-alias-id $ALIAS_ID \
  --session-id $SESSION_ID \
  --input-text "Generate GitHub Actions YAML for a Python application pipeline with build, test, Docker build, ECR push, and ECS deploy stages" \
  response.json

cat response.json
```

**Expected Results:**

- ✅ Generates valid GitHub Actions YAML
- ✅ Uses Template Validator Lambda to validate output
- ✅ Includes proper AWS credentials configuration

### 4. Verify Action Groups

```bash
AGENT_ID=$(terraform output -raw bedrock_agent_repo_scanner_id)

# List action groups for an agent
aws bedrock-agent list-agent-action-groups \
  --agent-id $AGENT_ID \
  --agent-version DRAFT
```

**Expected Results:**

- ✅ Repo Scanner Agent has Repository Ingestor action group
- ✅ Security Agent has Static Analyzer action group
- ✅ YAML Generator Agent has Template Validator action group
- ✅ PR Manager Agent has GitHub API action group

---

## End-to-End Workflow Validation

### 1. Test Orchestrator Lambda

```bash
LAMBDA_NAME=$(terraform output -raw lambda_orchestrator)
AGENT_IDS=$(terraform output -json agent_ids_map)

# Method 1: Pass JSON directly as string (recommended for AWS CLI v2)
aws lambda invoke \
  --function-name $LAMBDA_NAME \
  --cli-binary-format raw-in-base64-out \
  --payload "{\"task_id\": \"test-task-$(date +%s)\", \"repo_url\": \"https://github.com/octocat/Hello-World\", \"branch\": \"main\", \"agent_ids\": $AGENT_IDS}" \
  response.json

# Method 2: Use file with proper format flag (alternative)
cat > test_payload.json <<EOF
{
  "task_id": "test-task-$(date +%s)",
  "repo_url": "https://github.com/octocat/Hello-World",
  "branch": "main",
  "agent_ids": $AGENT_IDS
}
EOF

aws lambda invoke \
  --function-name $LAMBDA_NAME \
  --cli-binary-format raw-in-base64-out \
  --payload file://test_payload.json \
  response.json

cat response.json
```

**Expected Results:**

- ✅ Orchestrator starts workflow
- ✅ Creates task record in DynamoDB
- ✅ Invokes agents in sequence
- ✅ Updates task status

### 2. Check DynamoDB Task Tracking

```bash
TABLE_NAME=$(terraform output -raw dynamodb_table)

# Query recent tasks
aws dynamodb scan \
  --table-name $TABLE_NAME \
  --limit 5
```

**Expected Results:**

- ✅ Task records are created
- ✅ Status updates are tracked
- ✅ Results are stored

### 3. Full Workflow Test

**Note:** This requires a valid GitHub repository and configured GitHub PAT.

```bash
# Step 1: Invoke orchestrator
LAMBDA_NAME=$(terraform output -raw lambda_orchestrator)
TASK_ID="e2e-test-$(date +%s)"

aws lambda invoke \
  --function-name $LAMBDA_NAME \
  --payload "{
    \"task_id\": \"$TASK_ID\",
    \"repo_url\": \"https://github.com/YOUR_ORG/YOUR_REPO\",
    \"branch\": \"main\",
    \"agent_ids\": $(terraform output -json agent_ids_map)
  }" \
  response.json

# Step 2: Monitor task status
aws dynamodb get-item \
  --table-name $(terraform output -raw dynamodb_table) \
  --key "{\"task_id\": {\"S\": \"$TASK_ID\"}}"

# Step 3: Check CloudWatch logs
aws logs tail /aws/lambda/$LAMBDA_NAME --follow
```

**Expected Results:**

- ✅ Complete workflow executes
- ✅ Repository is analyzed
- ✅ Pipeline is designed
- ✅ YAML is generated and validated
- ✅ PR is created (if GitHub PAT is configured)

---

## Security Validation

### 1. IAM Permissions Review

```bash
# Check Lambda role permissions
aws iam get-role-policy \
  --role-name bedrock-ci-agent-lambda-exec \
  --policy-name bedrock-ci-agent-lambda-extra

# Check Bedrock agent role permissions
aws iam get-role-policy \
  --role-name bedrock-ci-agent-bedrock-agent-role \
  --policy-name bedrock-ci-agent-bedrock-agent-policy
```

**Validation Checklist:**

- ✅ Lambda functions have least privilege access
- ✅ Bedrock agent role only has necessary permissions
- ✅ Secrets Manager access is restricted to specific secret
- ✅ S3 access is restricted to templates bucket

### 2. Secrets Management

```bash
# Verify secret exists and is encrypted
SECRET_NAME=$(terraform output -raw github_pat_secret_name 2>/dev/null || echo "bedrock/github/pat")
aws secretsmanager describe-secret --secret-id $SECRET_NAME

# Check secret rotation (if configured)
aws secretsmanager describe-secret --secret-id $SECRET_NAME --query "RotationEnabled"
```

**Validation Checklist:**

- ✅ Secret is encrypted at rest
- ⚠️ Secret value is updated from placeholder
- ✅ Secret access is restricted to necessary roles

### 3. Network Security

```bash
# Check Lambda VPC configuration (if applicable)
aws lambda get-function-configuration \
  --function-name $(terraform output -raw lambda_orchestrator) \
  --query "VpcConfig"
```

**Note:** Current implementation doesn't use VPC. Consider adding for enhanced security.

### 4. Input Validation

Test Lambda functions with malicious inputs:

```bash
# Test with invalid repo URL
aws lambda invoke \
  --function-name $(terraform output -raw lambda_repo_ingestor) \
  --payload '{"repo_url": "javascript:alert(1)", "branch": "main"}' \
  response.json

# Test with extremely long input
aws lambda invoke \
  --function-name $(terraform output -raw lambda_template_validator) \
  --payload "{\"yaml_content\": \"$(python3 -c 'print("x" * 100000)')\"}" \
  response.json
```

**Expected Results:**

- ✅ Functions handle invalid input gracefully
- ✅ No crashes or security issues
- ✅ Appropriate error messages

---

## Monitoring & Observability Validation

### 1. CloudWatch Dashboard

```bash
# Get dashboard URL
terraform output cloudwatch_dashboard_url

# Verify dashboard exists
aws cloudwatch get-dashboard \
  --dashboard-name bedrock-ci-agent-dashboard
```

**Expected Results:**

- ✅ Dashboard exists
- ✅ Shows Lambda invocations, errors, duration
- ✅ Metrics are being collected

### 2. CloudWatch Log Groups

```bash
# List log groups
aws logs describe-log-groups \
  --log-group-name-prefix "/aws/lambda/bedrock-ci-agent" \
  --query "logGroups[*].logGroupName"
```

**Expected Results:**

- ✅ Log groups exist for all Lambda functions
- ✅ Retention is configured (14 days)
- ✅ Logs are being written

### 3. Metrics and Alarms

```bash
# List CloudWatch alarms (if configured)
aws cloudwatch describe-alarms \
  --alarm-name-prefix "bedrock-ci-agent"
```

**Note:** Alarms are not currently configured. Consider adding:

- Lambda error rate alarms
- Lambda duration alarms
- Bedrock agent invocation failures

---

## Automated Validation Script

Run the provided `validate.sh` script for automated validation:

```bash
chmod +x scripts/validate.sh
./scripts/validate.sh
```

The script will:

1. ✅ Validate Terraform configuration
2. ✅ Check all resources exist
3. ✅ Test Lambda functions
4. ✅ Test Bedrock agents
5. ✅ Verify IAM permissions
6. ✅ Check security configurations
7. ✅ Generate validation report

---

## Troubleshooting Common Issues

### Issue: Bedrock Agent Not Responding

**Solution:**

- Verify agent is prepared: `aws bedrock-agent prepare-agent --agent-id <ID>`
- Check agent alias exists: `aws bedrock-agent list-agent-aliases --agent-id <ID>`
- Verify IAM permissions for Bedrock agent role

### Issue: Lambda Function Timeout

**Solution:**

- Check Lambda timeout settings (currently 900s for most functions)
- Review CloudWatch logs for errors
- Verify dependencies are installed correctly

### Issue: "Invalid base64" Error When Invoking Lambda

**Solution:**

- AWS CLI v2 requires `--cli-binary-format raw-in-base64-out` flag for JSON payloads
- Use: `aws lambda invoke --cli-binary-format raw-in-base64-out --payload '{"key":"value"}' ...`
- Or pass JSON directly as string instead of using `file://`
- For AWS CLI v1, the flag is not needed

### Issue: GitHub API Lambda Fails

**Solution:**

- Verify GitHub PAT is updated in Secrets Manager
- Check PAT has necessary permissions (repo scope)
- Verify repository exists and is accessible

### Issue: Action Group Not Working

**Solution:**

- Verify OpenAPI spec is uploaded to S3
- Check action group is associated with correct Lambda
- Ensure Lambda has proper IAM permissions
- Verify agent version is DRAFT (or update to published version)

---

## Validation Checklist Summary

### Infrastructure

- [ ] All Terraform resources deployed successfully
- [ ] S3 bucket exists and contains OpenAPI specs
- [ ] DynamoDB table exists
- [ ] All 6 Lambda functions exist and are configured
- [ ] All 6 Bedrock agents exist
- [ ] IAM roles and policies are correct
- [ ] Secrets Manager secret exists

### Functionality

- [ ] Repository Ingestor Lambda works
- [ ] Static Analyzer Lambda works
- [ ] Template Validator Lambda works
- [ ] GitHub API Lambda works
- [ ] Orchestrator Lambda coordinates workflow
- [ ] Bedrock agents respond to queries
- [ ] Action groups are configured correctly

### Security

- [ ] IAM permissions follow least privilege
- [ ] Secrets are encrypted and properly managed
- [ ] Input validation works
- [ ] No hardcoded credentials

### Observability

- [ ] CloudWatch dashboard exists
- [ ] Log groups are configured
- [ ] Metrics are being collected

### End-to-End

- [ ] Complete workflow executes successfully
- [ ] Task tracking works in DynamoDB
- [ ] PR creation works (if GitHub PAT configured)

---

## Next Steps After Validation

1. **Update GitHub PAT** in Secrets Manager with real token
2. **Test with real repository** to validate end-to-end flow
3. **Review generated PRs** to ensure quality
4. **Set up CloudWatch Alarms** for production monitoring
5. **Configure Knowledge Bases** for improved agent accuracy
6. **Implement retry logic** in orchestrator
7. **Add human-in-the-loop gates** for production safety

---

## Support

For issues or questions:

1. Check CloudWatch logs for detailed error messages
2. Review Terraform outputs for resource IDs
3. Verify AWS permissions and Bedrock access
4. Consult AWS Bedrock documentation for agent-specific issues
