# Deep Analysis: Workflow Files Not Being Created

## Problem Statement

The end-to-end workflow is creating branches in GitHub but **not creating the `.github/workflows/ci-cd.yml` file** in those branches. This analysis identifies root causes and solutions.

## Root Cause Analysis

### Issue 1: Agent Not Calling create_file Operation

**Evidence:**
- Branches are being created (confirming `create_branch` works)
- No workflow files in branches (confirming `create_file` is not being called)
- OpenAPI spec has all three operations (verified via `verify_agent_operations.sh`)

**Possible Causes:**
1. Agent doesn't see `create_file` operation in action group
2. Agent instructions not clear enough about mandatory file creation
3. Agent skipping file creation step due to unclear instructions
4. YAML content not properly formatted for agent consumption

### Issue 2: Trace Event Parsing

The orchestrator may not be correctly parsing Bedrock trace events to detect action group invocations. Different trace event structures might exist.

### Issue 3: Agent Instruction Clarity

The agent instructions might be too verbose or not explicit enough about the mandatory nature of file creation.

## Solutions Implemented

### Solution 1: Enhanced Trace Logging

**File:** `lambda/orchestrator.py`

**Changes:**
- Added comprehensive trace event parsing to capture:
  - Action group invocation inputs (API path, HTTP method)
  - Action group invocation outputs (HTTP status codes)
  - Agent observations
- Logs all action group invocations with details
- Validates which operations were actually called

**Result:** We can now see exactly what operations the agent is calling.

### Solution 2: Improved Agent Instructions

**File:** `lambda/orchestrator.py` (orchestrator prompt) and `main.tf` (agent instructions)

**Changes:**
- Made instructions step-by-step with exact JSON parameter examples
- Emphasized that `create_file` is MANDATORY
- Provided YAML content in clear, copyable format
- Added explicit warnings about not skipping step 2

**Result:** Agent receives clearer, more actionable instructions.

### Solution 3: Post-Invocation Validation

**File:** `lambda/orchestrator.py`

**Changes:**
- After agent invocation, checks which operations were actually called
- Logs warnings if `create_file` was not called
- Provides diagnostic information about missing operations

**Result:** Immediate feedback when agent skips file creation.

### Solution 4: Diagnostic Scripts

**Files:** 
- `scripts/verify_agent_operations.sh` - Verifies operations are available
- `scripts/check_agent_actions.sh` - Checks CloudWatch logs for actual agent actions

**Result:** Easy debugging of agent behavior.

## Verification Steps

### Step 1: Verify Operations Are Available

```bash
./scripts/verify_agent_operations.sh
```

Should show:
- ✓ create_branch operation found
- ✓ create_file operation found
- ✓ create_pr operation found

### Step 2: Prepare the Agent

```bash
PR_MANAGER_AGENT_ID=$(terraform output -raw bedrock_agent_pr_manager_id)
aws bedrock-agent prepare-agent --agent-id $PR_MANAGER_AGENT_ID --region us-east-1
```

**Critical:** The agent must be prepared after any OpenAPI spec or instruction changes.

### Step 3: Redeploy Orchestrator Lambda

Since we updated `lambda/orchestrator.py`, redeploy:

```bash
# Rebuild Lambda package
cd build && zip -r lambda_functions.zip lambda_package/ && cd ..

# Update orchestrator
aws lambda update-function-code \
  --function-name $(terraform output -raw lambda_orchestrator) \
  --zip-file fileb://build/lambda_functions.zip
```

### Step 4: Run End-to-End Test

```bash
./scripts/e2e_test.sh
```

### Step 5: Check CloudWatch Logs

```bash
./scripts/check_agent_actions.sh
```

Or manually:
```bash
ORCHESTRATOR_FN=$(terraform output -raw lambda_orchestrator)
aws logs tail /aws/lambda/$ORCHESTRATOR_FN --follow
```

**Look for:**
- "PR Manager agent invoked X action group operations"
- "Operations called: branch=true, file=true, pr=true"
- If `file=false`, the agent is not calling create_file

## Expected Behavior After Fixes

1. **Orchestrator logs show:**
   ```
   PR Manager: owner=animesh303, repo=animesh303, yaml_length=1234
   YAML content preview (first 200 chars): name: CI/CD Pipeline...
   Invoking agent 8UOGAI8ZQO with session ...
   Agent trace - action: ...
   → Action Group Invocation: POST /create-branch
   ← Action Group Response: HTTP 200
   → Action Group Invocation: POST /create-file
   ← Action Group Response: HTTP 200
   → Action Group Invocation: POST /create-pr
   ← Action Group Response: HTTP 200
   PR Manager agent invoked 3 action group operations:
     - POST /create-branch (github-api-action)
     - POST /create-file (github-api-action)
     - POST /create-pr (github-api-action)
   Operations called: branch=true, file=true, pr=true
   ```

2. **GitHub repository shows:**
   - New branch: `ci-cd/add-pipeline`
   - File exists: `.github/workflows/ci-cd.yml` in that branch
   - Draft PR created with the workflow file

## If Issues Persist

### Check Agent Instructions

```bash
PR_MANAGER_AGENT_ID=$(terraform output -raw bedrock_agent_pr_manager_id)
aws bedrock-agent get-agent --agent-id $PR_MANAGER_AGENT_ID --region us-east-1 | jq -r '.instruction'
```

Verify it mentions:
- "STEP 2: Create Workflow File (MANDATORY - DO NOT SKIP)"
- Explicit mention of create_file operation

### Check Action Group Configuration

```bash
PR_MANAGER_AGENT_ID=$(terraform output -raw bedrock_agent_pr_manager_id)
aws bedrock-agent list-agent-action-groups \
  --agent-id $PR_MANAGER_AGENT_ID \
  --agent-version DRAFT \
  --region us-east-1
```

### Verify OpenAPI Spec in S3

```bash
BUCKET=$(terraform output -raw s3_bucket)
aws s3 cp s3://$BUCKET/openapi/github_pr_tool.yaml /tmp/check.yaml
grep -A 5 "create-file" /tmp/check.yaml
```

Should show the `/create-file` endpoint definition.

## Alternative Approach (If Agent Still Fails)

If the agent continues to skip file creation, consider:

1. **Direct Lambda Invocation:** Have the orchestrator call `create_file` directly if agent doesn't call it
2. **Two-Phase Approach:** Separate file creation from PR creation
3. **Validation Step:** After PR creation, verify file exists and recreate if missing

However, the current fixes should resolve the issue by making instructions clearer and adding better validation.

## Summary

The main issues were:
1. **Lack of visibility** into what operations the agent was actually calling
2. **Unclear instructions** about the mandatory nature of file creation
3. **No validation** to detect when file creation was skipped

All three issues have been addressed with:
- Enhanced trace logging
- Improved instructions with explicit examples
- Post-invocation validation
- Diagnostic tools

The agent should now create workflow files successfully.

