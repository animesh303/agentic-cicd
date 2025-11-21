# Using Cursor Rules for Workflow Generation

This document explains how to use Cursor AI to trigger workflow generation using natural language prompts.

## Overview

The `.cursorrules` file contains instructions that allow Cursor AI to understand and execute workflow generation requests. Instead of running the bash script manually, you can now use natural language prompts in Cursor.

## Prerequisites

1. **Infrastructure Deployed**: Run `terraform apply` to deploy the infrastructure
2. **AWS Credentials**: Configure AWS CLI with valid credentials
3. **Python Dependencies**: Install boto3 if using Python script (`pip install boto3`)

## Usage Examples

### Basic Workflow Generation

Simply ask Cursor:

```
Generate workflow for https://github.com/owner/repo
```

or

```
Trigger workflow generation for https://github.com/user/repo
```

### With Branch Specification

```
Create CI/CD pipeline for https://github.com/owner/repo on branch develop
```

### With Progress Monitoring

```
Generate workflow for https://github.com/owner/repo and monitor progress
```

## What Happens Behind the Scenes

When you make a request, Cursor AI will:

1. **Check Prerequisites**

   - Verify AWS CLI is installed and configured
   - Verify Terraform outputs are available
   - Check for required dependencies

2. **Get Infrastructure Information**

   - Retrieve orchestrator Lambda function name
   - Get agent IDs from Terraform outputs
   - Get DynamoDB table name

3. **Generate Task ID**

   - Create unique task ID: `workflow-gen-{timestamp}-{random-hex}`

4. **Invoke Orchestrator**

   - Create payload with task_id, repo_url, branch, and agent_ids
   - Invoke orchestrator Lambda function asynchronously

5. **Monitor Progress** (if requested)
   - Poll DynamoDB for task status
   - Display real-time progress updates
   - Show final results when complete

## Response Format

After triggering, you'll see:

- ✓ Task ID generated
- Repository and branch information
- Lambda invocation status
- Task ID for tracking
- Instructions for monitoring (if not auto-monitoring)

## Workflow Steps

The orchestrator executes these steps in order:

1. **repo_ingestor** - Downloads and analyzes repository structure
2. **repo_scanner** - Scans repository for languages, frameworks, build systems
3. **static_analyzer** - Performs security and dependency analysis
4. **pipeline_designer** - Designs CI/CD pipeline architecture
5. **security_compliance** - Validates security and compliance requirements
6. **yaml_generator_attempt_1** - First attempt at generating workflow YAML
7. **yaml_generator_attempt_2** - Second attempt if first fails
8. **template_validator** - Validates generated YAML syntax
9. **pr_manager** - Prepares pull request content
10. **github_operations** - Creates pull request on GitHub

## Monitoring Progress

### Automatic Monitoring

If you request monitoring, Cursor will:

- Poll DynamoDB every 5 seconds
- Display real-time status updates
- Show completed steps
- Display final results

### Manual Monitoring

You can check progress manually:

```bash
# Get task status from DynamoDB
aws dynamodb get-item \
  --table-name $(terraform output -raw dynamodb_table) \
  --key "{\"task_id\": {\"S\": \"<task_id>\"}}" \
  --output json | jq
```

Or use the Python script:

```bash
python3 scripts/trigger_workflow_generation.py <repo_url> --monitor
```

## Troubleshooting

### "Terraform outputs not available"

**Solution**: Run `terraform apply` first to deploy infrastructure

### "AWS credentials not configured"

**Solution**: Configure AWS CLI: `aws configure`

### "Lambda invocation failed"

**Solution**:

- Check AWS credentials and permissions
- Verify Lambda function exists: `terraform output lambda_orchestrator`
- Check CloudWatch logs for the orchestrator Lambda

### "Agent IDs not found"

**Solution**: Ensure all Bedrock agents are deployed. Check Terraform outputs:

```bash
terraform output agent_ids_map
```

## Advanced Usage

### Using Python Script Directly

You can also use the Python script directly:

```bash
# Basic usage
python3 scripts/trigger_workflow_generation.py https://github.com/owner/repo

# With branch
python3 scripts/trigger_workflow_generation.py https://github.com/owner/repo --branch develop

# With monitoring
python3 scripts/trigger_workflow_generation.py https://github.com/owner/repo --monitor

# Check prerequisites only
python3 scripts/trigger_workflow_generation.py https://github.com/owner/repo --check-only
```

### Programmatic Usage

```python
from scripts.trigger_workflow_generation import trigger_workflow_generation

result = trigger_workflow_generation(
    repo_url="https://github.com/owner/repo",
    branch="main",
    monitor=True
)

print(f"Task ID: {result['task_id']}")
print(f"Status: {result.get('final_status', {}).get('status')}")
```

## Comparison: Bash Script vs Cursor Rules

| Feature              | Bash Script | Cursor Rules        |
| -------------------- | ----------- | ------------------- |
| Interactive prompts  | ✓           | ✓ (via Cursor chat) |
| Natural language     | ✗           | ✓                   |
| Progress monitoring  | ✓           | ✓                   |
| Error handling       | ✓           | ✓                   |
| Programmatic use     | Limited     | ✓ (Python script)   |
| Integration with IDE | ✗           | ✓                   |

## Tips

1. **Be Specific**: Include the full repository URL in your prompt
2. **Specify Branch**: Mention the branch if it's not "main"
3. **Request Monitoring**: Ask to "monitor progress" if you want real-time updates
4. **Check Prerequisites**: Ask Cursor to "check prerequisites" before triggering

## Example Conversation

```
You: Generate workflow for https://github.com/myorg/myrepo

Cursor: Checking prerequisites...
✓ AWS CLI installed and configured
✓ Terraform outputs available

Retrieving infrastructure information...
✓ Orchestrator Lambda: bedrock-ci-agent-orchestrator
✓ Agent IDs retrieved

Generating task ID...
Task ID: workflow-gen-1704067200-a1b2c3d4

Invoking orchestrator Lambda...
✓ Orchestrator Lambda invoked successfully

Workflow generation started. This may take 5-15 minutes.
Task ID for tracking: workflow-gen-1704067200-a1b2c3d4

To monitor progress, check DynamoDB table: agentic-cicd-tasks
Query key: task_id = workflow-gen-1704067200-a1b2c3d4
```
