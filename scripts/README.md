# Scripts Directory

This directory contains utility scripts for building, testing, and using the Agentic CI/CD pipeline generator.

## build_lambda.sh

Builds the Lambda functions deployment package.

### Usage

```bash
./scripts/build_lambda.sh
```

### What it does

1. Creates the build directory structure
2. Copies all Python files from `lambda/` directory
3. Installs dependencies from `lambda/requirements.txt` (Linux-compatible for Lambda runtime)
4. Creates a deployment package ZIP file at `build/lambda_functions.zip`

### Requirements

- Python 3.x
- pip
- Access to the `lambda/` directory with Python source files
- `lambda/requirements.txt` (optional, but recommended)

### Output

The script creates:

- `build/lambda_package/` - Temporary build directory (can be cleaned up)
- `build/lambda_functions.zip` - Final deployment package for all Lambda functions

### When to run

Run this script:

- Before running `terraform plan` or `terraform apply`
- After making changes to Lambda function code
- After updating `lambda/requirements.txt`
- In CI/CD pipelines before Terraform deployment

### Notes

- The script automatically handles platform-specific package installation for Lambda's Linux runtime
- The build directory is cleaned before each build
- The script exits with an error code if any step fails

## trigger_workflow_generation.sh

Interactive script to trigger GitHub workflow generation for a target repository.

### Usage

```bash
./scripts/trigger_workflow_generation.sh
```

### What it does

1. Prompts for target repository URL
2. Optionally prompts for branch name (defaults to "main")
3. Retrieves orchestrator Lambda function name and agent IDs from Terraform outputs
4. Invokes the orchestrator Lambda to generate GitHub Actions workflows
5. Displays progress and results

### Requirements

- AWS CLI installed and configured
- Terraform outputs available (run `terraform apply` first)
- Valid AWS credentials with permissions to invoke Lambda functions
- `jq` (optional but recommended for better JSON parsing)

### Workflow

The orchestrator agent will:

1. **Analyze the repository** - Scan repository structure, detect languages, frameworks, and build systems
2. **Design CI/CD pipeline** - Create appropriate stages for build, test, scan, container build, ECR push, and ECS deployment
3. **Security & Compliance** - Validate SAST/SCA scanning, secrets scanning, and IAM permissions
4. **Generate YAML** - Create GitHub Actions workflow YAML with proper AWS authentication and security stages
5. **Create Pull Request** - Generate a PR with the workflow file and comprehensive documentation

### Example

```bash
$ ./scripts/trigger_workflow_generation.sh

==========================================
GitHub Workflow Generation Trigger
==========================================

ℹ Checking Prerequisites...
✓ AWS CLI installed
✓ AWS credentials configured (Account: 123456789012)
✓ Terraform installed
✓ Terraform outputs available
✓ jq installed (for JSON processing)

==========================================
Retrieving Infrastructure Information
==========================================

✓ Orchestrator Lambda: bedrock-ci-agent-orchestrator
✓ Agent IDs retrieved

Available agents:
  - repo_scanner: AGENT_ID_1
  - pipeline_designer: AGENT_ID_2
  - security_compliance: AGENT_ID_3
  - yaml_generator: AGENT_ID_4
  - pr_manager: AGENT_ID_5

==========================================
Repository Information
==========================================

Enter GitHub repository URL: https://github.com/owner/repo
✓ Repository URL validated: https://github.com/owner/repo
ℹ Owner: owner
ℹ Repository: repo
Enter branch name [default: main]: main
✓ Target branch: main
ℹ Task ID: workflow-gen-1234567890-abc123

==========================================
Confirmation
==========================================

Repository: https://github.com/owner/repo
Branch: main
Task ID: workflow-gen-1234567890-abc123

Proceed with workflow generation? [y/N]: y

==========================================
Invoking Orchestrator Agent
==========================================

ℹ This may take 5-15 minutes to complete...
✓ Orchestrator invocation completed (duration: 450s)
✓ Workflow generation completed successfully!

ℹ Workflow steps completed: 6
  ✓ repo_ingestor
  ✓ repo_scanner
  ✓ static_analyzer
  ✓ pipeline_designer
  ✓ security_compliance
  ✓ yaml_generator
  ✓ template_validator
  ✓ github_operations

✓ GitHub pull request created successfully!
ℹ Check the repository for the new PR with the generated workflow
ℹ Task ID for tracking: workflow-gen-1234567890-abc123
```

### Output

- Response JSON saved to `/tmp/orchestrator_response_<task_id>_<timestamp>.json`
- Task ID for tracking in DynamoDB
- Status of each workflow step
- GitHub PR creation status

### Notes

- The script validates GitHub repository URLs before proceeding
- It checks all prerequisites before attempting to invoke the orchestrator
- The orchestrator Lambda has a 15-minute timeout, so the script waits up to 20 minutes
- Task status can be tracked in the DynamoDB table using the provided task ID
- If GitHub operations fail, check the response file for detailed error messages
