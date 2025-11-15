# Root Cause Found: Workflow Files Not Being Created

## Critical Discovery

After analyzing CloudWatch logs, I found the **root cause**:

### The Problem

The PR Manager agent is:
1. ✅ **Creating branches** successfully
2. ❌ **NOT calling `create_file` operation** 
3. ❌ **Trying to create PRs with empty branches**

### Evidence from Logs

GitHub API Lambda logs show:
```
Error creating PR: GitHub API validation error: Validation Failed: 
{'resource': 'PullRequest', 'code': 'custom', 
 'message': 'No commits between main and ci-cd/add-pipeline'}
```

This error occurs because:
- The branch `ci-cd/add-pipeline` exists (created by agent)
- But the branch has **no commits** (no files were added)
- GitHub rejects PR creation when there are no commits between branches

### Why This Happens

The agent is **not calling the `create_file` operation** even though:
- ✅ The operation exists in the OpenAPI spec (verified)
- ✅ The operation is available in the action group (verified)
- ✅ Instructions explicitly tell the agent to use it

**Possible reasons:**
1. Agent doesn't see the operation (needs to be prepared)
2. Agent instructions not clear enough
3. Agent is skipping the step for some reason

## Solution Implemented

### 1. Enhanced Logging
- Added trace event parsing to see exactly which operations the agent calls
- Logs action group invocations with API paths
- Validates which operations were actually called

### 2. Fallback Mechanism
**File:** `lambda/orchestrator.py`

If the agent creates a branch but doesn't create the file, the orchestrator will:
1. Detect that `create_file` was not called
2. Directly invoke the GitHub API Lambda to create the file
3. Log the fallback action

This ensures workflow files are created even if the agent skips the step.

### 3. Updated Instructions
- Made instructions more explicit with exact JSON examples
- Emphasized that `create_file` is MANDATORY
- Added step-by-step format

## Next Steps

### 1. Apply Terraform Changes
```bash
terraform apply
```
This adds `GITHUB_API_FUNCTION_NAME` environment variable to orchestrator.

### 2. Redeploy Orchestrator Lambda
```bash
cd build && zip -r lambda_functions.zip lambda_package/ && cd ..
aws lambda update-function-code \
  --function-name $(terraform output -raw lambda_orchestrator) \
  --zip-file fileb://build/lambda_functions.zip
```

### 3. Prepare Agent (if not done)
```bash
PR_MANAGER_AGENT_ID=$(terraform output -raw bedrock_agent_pr_manager_id)
aws bedrock-agent prepare-agent --agent-id $PR_MANAGER_AGENT_ID --region us-east-1
```

### 4. Test Again
```bash
./scripts/e2e_test.sh
```

## Expected Behavior

After these fixes:

1. **If agent calls create_file:**
   - Workflow file is created by agent ✓
   - PR is created successfully ✓

2. **If agent doesn't call create_file (fallback):**
   - Orchestrator detects missing operation
   - Orchestrator creates file directly via Lambda ✓
   - PR can then be created successfully ✓

## Verification

After running the test, check logs for:
- `"Operations called: branch=true, file=true, pr=true"` - Agent did everything
- `"FALLBACK: Creating workflow file directly via Lambda"` - Fallback was used
- `"SUCCESS: Workflow file created via fallback!"` - Fallback succeeded

The fallback ensures workflow files are created **regardless** of agent behavior.

