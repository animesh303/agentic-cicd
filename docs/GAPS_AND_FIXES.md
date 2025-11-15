# Gaps Analysis and Fixes

## Problem Summary

The end-to-end solution flow was creating branches in the GitHub repository but **not creating the GitHub Actions workflow files** in those branches. This document identifies the gaps between intent and implementation, and the fixes applied.

## Root Cause Analysis

### Gap 1: Missing OpenAPI Operations

**Issue:** The OpenAPI specification (`openapi/github_pr_tool.yaml`) only exposed the `create_pr` operation. However, the orchestrator was instructing the PR Manager agent to use `create_file` and `create_branch` operations, which didn't exist in the API specification.

**Impact:** The agent couldn't follow the orchestrator's instructions because the required operations weren't available via the action group.

**Location:** `openapi/github_pr_tool.yaml`

### Gap 2: Orchestrator Instructions Mismatch

**Issue:** The orchestrator was telling the agent to "use the create_file operation first", but this operation wasn't available in the OpenAPI spec. Additionally, the orchestrator wasn't extracting YAML content from markdown code blocks that the YAML Generator agent might return.

**Impact:**

- Agent couldn't execute the requested workflow
- YAML content might not be properly extracted if returned in markdown format

**Location:** `lambda/orchestrator.py` (line 323)

### Gap 3: Unclear Agent Instructions

**Issue:** The PR Manager agent instructions were vague about:

- How to extract YAML from markdown code blocks
- The exact sequence of operations (branch → file → PR)
- How to properly use the `files` array parameter

**Impact:** Agent might create branches but fail to add files, or might not extract YAML content correctly.

**Location:** `main.tf` (PR Manager agent instructions)

## Fixes Applied

### Fix 1: Added Missing Operations to OpenAPI Spec

**File:** `openapi/github_pr_tool.yaml`

**Changes:**

- Added `/create-branch` endpoint with `createBranch` operation
- Added `/create-file` endpoint with `createFile` operation
- Both operations follow the same pattern as `create_pr` and are properly documented

**Result:** The agent now has access to all three operations needed for the workflow.

### Fix 2: Enhanced Orchestrator YAML Extraction

**File:** `lambda/orchestrator.py`

**Changes:**

- Added YAML extraction logic to handle markdown code blocks (`yaml ... `)
- Added fallback logic to extract YAML-like content even if not in code blocks
- Enhanced instructions to be more explicit about the workflow steps
- Added owner/repo extraction from URL for clarity

**Result:** The orchestrator now properly extracts YAML content and provides clearer instructions to the agent.

### Fix 3: Clarified PR Manager Agent Instructions

**File:** `main.tf`

**Changes:**

- Rewrote agent instructions with explicit step-by-step workflow
- Added clear requirements for YAML extraction
- Specified the exact order of operations: branch → file → PR
- Added critical requirements section emphasizing file creation

**Result:** The agent now has clear, actionable instructions that match the available operations.

### Fix 4: Re-Prepare Agents on OpenAPI Schema Changes

**File:** `main.tf`

**Changes:**

- Added a `schema_hashes` trigger to `null_resource.prepare_agents` that hashes all OpenAPI documents.
- Any change to `openapi/*.yaml` now forces Terraform to re-run `aws bedrock-agent prepare-agent`, guaranteeing that agents load the latest schema.

**Result:** Updating the OpenAPI specs automatically refreshes the agent action groups, so new operations become available without manual intervention.

### Fix 5: Validate GitHub Branches and Workflow Files in E2E Tests

**File:** `scripts/e2e_test.sh`

**Changes:**

- Parse repository owner/name from `TEST_REPO_URL`.
- After a workflow run completes, call the GitHub REST API to ensure branch `ci-cd/add-pipeline` exists.
- Fetch `.github/workflows/ci-cd.yml` from the branch via `raw.githubusercontent.com` and fail the test suite if it is missing.
- Record the verification results in `test_results` JSON for traceability.

**Result:** The test suite now fails whenever GitHub artifacts are absent, preventing false positives.

### Fix 6: Fallback to GitHub API Lambda When Agent Misses Operations

**File:** `lambda/orchestrator.py`

**Changes:**

- Detect when the PR Manager agent does not invoke `create_branch`, `create_file`, and `create_pr` calls or explicitly reports missing operations.
- Added `_normalize_github_lambda_response` and `execute_github_workflow()` helpers that call the GitHub API Lambda directly to create the branch, workflow file, and draft PR.
- Record fallback usage in `workflow_steps` so tests and logs can surface when recovery happened.

**Result:** Even if the agent temporarily lacks operations, the orchestrator guarantees that GitHub branches and workflow files are created, aligning runtime behavior with the intended requirements.

### Gap 4: Agent Schema Updates Did Not Trigger Re-Preparation

**Issue:** The Terraform `null_resource.prepare_agents` only triggered on instruction changes. Updating any OpenAPI schema (for example `github_pr_tool.yaml`) uploaded the new spec to S3, but the agent continued using its cached schema because `prepare-agent` never re-ran automatically.

**Impact:** Even after deploying the new operations, the PR Manager agent still reported that only `create_pr` was available, so no branches or workflow files were created.

**Location:** `main.tf`

### Gap 5: End-to-End Tests Did Not Verify GitHub Artifacts

**Issue:** The e2e test script considered a run successful if the orchestrator Lambda returned success or if DynamoDB showed `completed`. It never checked GitHub to confirm that the branch and workflow file actually existed, leading to false positives.

**Location:** `scripts/e2e_test.sh`

### Gap 6: Orchestrator Did Not Recover When Agents Lacked Operations

**Issue:** If the PR Manager agent could not call the action group (because operations were missing or throttled), the orchestrator logged a warning but still returned success. No fallback attempted to create the branch/file/PR directly, so GitHub remained untouched.

**Location:** `lambda/orchestrator.py`

## Expected Behavior After Fixes

1. **Repository Analysis:** ✅ Works (no changes needed)
2. **Pipeline Design:** ✅ Works (no changes needed)
3. **YAML Generation:** ✅ Works (no changes needed)
4. **PR Creation Workflow:**
   - ✅ Agent creates a new branch using `create_branch`
   - ✅ Agent creates `.github/workflows/ci-cd.yml` file using `create_file` with the extracted YAML content
   - ✅ Agent creates a draft PR using `create_pr` pointing to the branch with the file

## Testing Recommendations

After applying these fixes:

1. **Update the OpenAPI spec in S3:**

   ```bash
   aws s3 cp openapi/github_pr_tool.yaml s3://<bucket>/openapi/github_pr_tool.yaml
   ```

2. **Update the Bedrock Agent Action Group:**

   - Go to Bedrock Console → Agents → PR Manager Agent
   - Update the action group to use the new OpenAPI spec
   - Prepare the agent

3. **Update Agent Instructions (if using Terraform):**

   ```bash
   terraform apply
   ```

4. **Run End-to-End Test:**

   ```bash
   ./scripts/e2e_test.sh
   ```

5. **Verify in GitHub:**
   - Check that branches are created
   - **Verify that `.github/workflows/ci-cd.yml` file exists in the branch**
   - Verify that PRs are created with the workflow file

## Additional Considerations

### Alternative Approach (Not Implemented)

The `create_pr` operation already supports a `files` array parameter that can create files as part of PR creation. However, the current approach (separate operations) is clearer and gives the agent more control.

### Future Enhancements

1. Add validation to ensure YAML content is valid before creating the file
2. Add retry logic if file creation fails
3. Add logging to track which operations the agent is calling
4. Consider adding a "verify_file_exists" operation to check if files were created successfully

## Summary

The main issue was a **mismatch between what the orchestrator instructed the agent to do and what operations were available in the OpenAPI specification**. By adding the missing operations and clarifying instructions, the agent should now be able to:

1. ✅ Create branches
2. ✅ Create workflow files in those branches
3. ✅ Create PRs with the workflow files

The fixes ensure that the implementation matches the intent: creating GitHub Actions workflow files in branches before opening PRs.

## Troubleshooting: Branches Created But No Workflow Files

If you're seeing branches created but no workflow files, follow these steps:

### Step 1: Verify Operations Are Available

Run the diagnostic script:

```bash
./scripts/verify_agent_operations.sh
```

This will check:

- If the OpenAPI spec is in S3
- If the new operations (create_branch, create_file, create_pr) are in the spec
- If the agent action group is configured correctly

### Step 2: Prepare the Agent

If operations exist but agent still doesn't use them:

```bash
# Get agent ID
PR_MANAGER_AGENT_ID=$(terraform output -raw bedrock_agent_pr_manager_id)

# Prepare the agent
aws bedrock-agent prepare-agent --agent-id $PR_MANAGER_AGENT_ID --region us-east-1
```

### Step 3: Check CloudWatch Logs

Check the orchestrator Lambda logs to see what the agent is actually doing:

```bash
# Get orchestrator function name
ORCHESTRATOR_FN=$(terraform output -raw lambda_orchestrator)

# Tail the logs
aws logs tail /aws/lambda/$ORCHESTRATOR_FN --follow
```

Look for:

- "PR Manager: owner=..., repo=..., yaml_length=..." - confirms YAML is being passed
- "YAML content preview" - shows the YAML being sent to the agent
- Any error messages from the agent

### Step 4: Verify YAML Content

The orchestrator now validates that YAML content is not empty. If you see:

```
ERROR: YAML content is too short or empty
```

This means the YAML Generator agent didn't produce valid YAML. Check the YAML Generator agent's response in the workflow steps.

### Step 5: Check Agent Instructions

Verify the agent instructions were updated:

```bash
PR_MANAGER_AGENT_ID=$(terraform output -raw bedrock_agent_pr_manager_id)
aws bedrock-agent get-agent --agent-id $PR_MANAGER_AGENT_ID --region us-east-1 | jq -r '.instruction'
```

The instructions should mention:

- "STEP 2: Create the workflow file (THIS IS MANDATORY - DO NOT SKIP THIS STEP)"
- Explicit mention of the create_file operation

### Common Issues

1. **Agent not prepared after OpenAPI update**: Run `terraform apply` then manually prepare the agent
2. **YAML content empty**: Check YAML Generator agent output
3. **Agent skipping file creation**: Check agent instructions and ensure they're updated
4. **Operations not visible**: Verify OpenAPI spec is in S3 and action group references it correctly
