# GitHub Personal Access Token (PAT) Setup Guide

## Overview
The GitHub API Lambda requires a valid GitHub Personal Access Token (PAT) to authenticate API requests. Currently, the secret is set to a placeholder value, which causes 401 Unauthorized errors.

## Step 1: Create a GitHub Personal Access Token

1. **Go to GitHub Settings:**
   - Navigate to: https://github.com/settings/tokens
   - Or: GitHub Profile → Settings → Developer settings → Personal access tokens → Tokens (classic)

2. **Generate a new token:**
   - Click "Generate new token" → "Generate new token (classic)"
   - Give it a descriptive name (e.g., "Bedrock CI/CD Agent")
   - Set expiration (recommended: 90 days or custom)
   - Select the following scopes:
     - ✅ `repo` (Full control of private repositories)
       - This includes: `repo:status`, `repo_deployment`, `public_repo`, `repo:invite`, `security_events`
     - ✅ `workflow` (Update GitHub Action workflows)
   - Click "Generate token"

3. **Copy the token immediately:**
   - ⚠️ **Important:** GitHub only shows the token once. Copy it now!
   - The token will look like: `ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx`

## Step 2: Update AWS Secrets Manager

You have two options to update the secret:

### Option A: Using AWS CLI (Recommended)

```bash
# Get the secret name from Terraform
SECRET_NAME=$(terraform output -raw github_pat_secret_name 2>/dev/null || echo "bedrock/github/pat")

# Update the secret with your GitHub PAT
aws secretsmanager update-secret \
  --secret-id "$SECRET_NAME" \
  --secret-string '{"token":"YOUR_GITHUB_PAT_HERE"}' \
  --region us-east-1

# Replace YOUR_GITHUB_PAT_HERE with your actual token (e.g., ghp_xxxxxxxxxxxxx)
```

**Example:**
```bash
aws secretsmanager update-secret \
  --secret-id "bedrock/github/pat" \
  --secret-string '{"token":"ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"}' \
  --region us-east-1
```

### Option B: Using AWS Console

1. **Navigate to AWS Secrets Manager:**
   - Go to: https://console.aws.amazon.com/secretsmanager/
   - Select your region (e.g., us-east-1)

2. **Find the secret:**
   - Search for: `bedrock/github/pat`
   - Click on the secret name

3. **Update the secret value:**
   - Click "Retrieve secret value" to view current value
   - Click "Edit"
   - Replace the JSON value:
     ```json
     {
       "token": "ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
     }
     ```
   - Replace `ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx` with your actual token
   - Click "Save"

## Step 3: Verify the Secret

Verify that the secret was updated correctly:

```bash
# Get the secret name
SECRET_NAME=$(terraform output -raw github_pat_secret_name 2>/dev/null || echo "bedrock/github/pat")

# Retrieve and verify (token will be masked)
aws secretsmanager get-secret-value \
  --secret-id "$SECRET_NAME" \
  --region us-east-1 \
  --query 'SecretString' \
  --output text | jq '.'
```

**Expected output:**
```json
{
  "token": "ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
}
```

## Step 4: Test the GitHub API Lambda

Test that the GitHub API Lambda can now authenticate:

```bash
# Test with a simple operation (create_branch)
aws lambda invoke \
  --function-name bedrock-ci-agent-github-api \
  --cli-binary-format raw-in-base64-out \
  --payload '{
    "operation": "create_branch",
    "owner": "octocat",
    "repo": "Hello-World",
    "branch": "test-branch",
    "base_branch": "main"
  }' \
  /tmp/github_api_test.json

# Check the response
cat /tmp/github_api_test.json | jq '.'
```

**Expected response (success):**
```json
{
  "status": "success",
  "branch": "test-branch"
}
```

**If you still get 401 errors:**
- Verify the token is correct (no extra spaces)
- Check that the token has the required scopes (`repo`, `workflow`)
- Ensure the token hasn't expired
- Verify the secret name matches: `bedrock/github/pat`

## Security Best Practices

1. **Token Expiration:**
   - Set tokens to expire after a reasonable period (90 days recommended)
   - Set calendar reminders to rotate tokens before expiration

2. **Least Privilege:**
   - Only grant the minimum scopes needed (`repo`, `workflow`)
   - Don't grant `admin:repo_hook` or `delete_repo` unless necessary

3. **Token Rotation:**
   - Rotate tokens periodically (every 90 days)
   - Update the secret in AWS Secrets Manager when rotating

4. **Monitoring:**
   - Monitor CloudWatch logs for authentication failures
   - Set up alerts for 401 errors

## Troubleshooting

### Error: "401 Client Error: Unauthorized"

**Possible causes:**
1. Token is incorrect or has extra spaces
2. Token has expired
3. Token doesn't have required scopes
4. Secret format is incorrect (should be JSON with "token" key)

**Solution:**
```bash
# Verify secret format
aws secretsmanager get-secret-value \
  --secret-id "bedrock/github/pat" \
  --query 'SecretString' \
  --output text | jq '.'
```

### Error: "Failed to retrieve GitHub token"

**Possible causes:**
1. Secret doesn't exist in Secrets Manager
2. Lambda doesn't have permission to read the secret
3. Secret name mismatch

**Solution:**
```bash
# Check if secret exists
aws secretsmanager describe-secret --secret-id "bedrock/github/pat"

# Verify Lambda IAM role has secretsmanager:GetSecretValue permission
# (This should be configured in Terraform)
```

## Alternative: Using Terraform to Set the Secret

If you prefer to manage the secret via Terraform (not recommended for production):

```hcl
# In terraform.tfvars or as a variable
# ⚠️ WARNING: Don't commit this to version control!

resource "aws_secretsmanager_secret_version" "github_pat_value" {
  secret_id     = aws_secretsmanager_secret.github_pat.id
  secret_string = jsonencode({ 
    token = var.github_pat_token  # Pass via -var or TF_VAR_ environment variable
  })
}
```

**Usage:**
```bash
terraform apply -var="github_pat_token=ghp_xxxxxxxxxxxxx"
```

**⚠️ Security Note:** Never commit tokens to version control. Use AWS Secrets Manager or environment variables.

