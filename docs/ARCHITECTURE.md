# Multi-Agent Architecture Implementation

## Overview

This implementation provides a complete multi-agent architecture for automated CI/CD pipeline generation using Amazon Bedrock Agents. The system consists of 6 specialized agents, 5 Lambda functions, and an orchestrator to coordinate the workflow.

## Architecture Components

### 1. Orchestrator/Controller

**Lambda Function:** `orchestrator.py`

- Coordinates all agents and tracks tasks
- Manages workflow between different agents
- Uses DynamoDB for task state tracking
- Invokes agents in sequence based on workflow requirements

### 2. Repository Ingestor

**Lambda Function:** `repo_ingestor.py`

- Clones repository from GitHub
- Extracts manifest files:
  - Dockerfiles
  - Package manifests (package.json, requirements.txt, pom.xml, etc.)
  - Infrastructure as Code (Terraform, CloudFormation)
  - Kubernetes manifests
  - Helm charts
- Returns structured JSON with all extracted content

### 3. Static Analyzers & Scanners

**Lambda Function:** `static_analyzer.py`

- Analyzes Dockerfiles for best practices and security issues
- Detects dependencies from manifest files
- Identifies test frameworks and test files
- Provides vulnerability scanning foundation (ready for Trivy/Snyk integration)

### 4. Template Engine & Validator

**Lambda Function:** `template_validator.py`

- Validates GitHub Actions YAML syntax
- Checks for security issues (hardcoded secrets, etc.)
- Validates secrets usage
- Checks IAM permissions and least privilege
- Returns validation results with errors and warnings

## Bedrock Agents

### 1. Repo Scanner Agent

**Purpose:** Scans repositories and builds inventory

- Identifies languages, frameworks, build systems
- Detects containers, tests, infrastructure targets
- Uses Repository Ingestor Lambda via action group

### 2. Pipeline Designer Agent

**Purpose:** Designs CI/CD pipeline stages

- Decides build/test/lint/scan/image stages
- Designs matrix strategy, caching, artifacts
- Considers repository analysis results

### 3. Security & Compliance Agent

**Purpose:** Ensures security and compliance

- Validates SAST/SCA scanning inclusion
- Ensures secrets scanning
- Validates least privilege IAM permissions
- Uses Static Analyzer Lambda via action group

### 4. YAML Generator Agent

**Purpose:** Generates GitHub Actions YAML

- Converts pipeline design to concrete YAML
- Includes proper AWS credentials configuration
- Manages secrets properly
- Uses Template Validator Lambda via action group for validation

### 5. PR Manager Agent

**Purpose:** Creates GitHub PRs

- Creates pull requests with generated workflows
- Populates PR description with rationale
- Lists required secrets and permissions
- Uses GitHub API via OpenAPI action group

### 6. Feedback Agent

**Purpose:** Analyzes CI run logs and suggests improvements

- Reads GitHub Actions run logs
- Suggests caching optimizations
- Identifies parallelization opportunities
- Provides build time reduction recommendations

## Workflow

```
1. User invokes Orchestrator Lambda
   ↓
2. Orchestrator invokes Repo Scanner Agent
   ↓
3. Repo Scanner Agent calls Repository Ingestor Lambda
   ↓
4. Orchestrator invokes Static Analyzer Lambda (direct)
   ↓
5. Orchestrator invokes Pipeline Designer Agent
   ↓
6. Orchestrator invokes Security & Compliance Agent
   ↓
7. Orchestrator invokes YAML Generator Agent
   ↓
8. YAML Generator Agent calls Template Validator Lambda
   ↓
9. Orchestrator invokes PR Manager Agent
   ↓
10. PR Manager Agent creates GitHub PR via API
```

## Infrastructure Components

### AWS Resources

1. **S3 Bucket** (`templates`)

   - Stores OpenAPI specifications
   - Stores CI/CD templates
   - Stores Lambda deployment packages

2. **DynamoDB Table** (`task_tracking`)

   - Tracks workflow execution state
   - Stores task results
   - Enables workflow resumption

3. **Lambda Functions**

   - `repo_scanner` - Original scanner (backward compatibility)
   - `repo_ingestor` - Enhanced repository ingestion
   - `static_analyzer` - Security and dependency analysis
   - `template_validator` - YAML validation
   - `orchestrator` - Workflow coordination

4. **Bedrock Agents** (6 agents)

   - Each agent has specialized instructions
   - Connected to Lambda functions via action groups
   - Can invoke other agents via Bedrock runtime API

5. **IAM Roles & Policies**

   - Lambda execution role with necessary permissions
   - Bedrock agent role for invoking Lambdas and agents
   - Least privilege access patterns

6. **Secrets Manager**
   - Stores GitHub Personal Access Token
   - Accessed by agents via action groups

## Usage

### Invoking the Orchestrator

```python
import boto3

lambda_client = boto3.client('lambda')

response = lambda_client.invoke(
    FunctionName='bedrock-ci-agent-orchestrator',
    Payload=json.dumps({
        'task_id': 'unique-task-id',
        'repo_url': 'https://github.com/owner/repo',
        'branch': 'main',
        'agent_ids': {
            'repo_scanner': 'agent-id-1',
            'pipeline_designer': 'agent-id-2',
            'security_compliance': 'agent-id-3',
            'yaml_generator': 'agent-id-4',
            'pr_manager': 'agent-id-5'
        }
    })
)
```

### Direct Agent Invocation

```python
import boto3

bedrock_runtime = boto3.client('bedrock-agent-runtime')

response = bedrock_runtime.invoke_agent(
    agentId='repo-scanner-agent-id',
    agentAliasId='TSTALIASID',
    sessionId='session-123',
    inputText='Analyze repository: https://github.com/example/repo'
)
```

## Deployment

1. **Update terraform.tfvars** with your values
2. **Run terraform init**
3. **Run terraform apply**
4. **Update GitHub PAT** in Secrets Manager
5. **Get agent IDs** from Terraform outputs
6. **Invoke orchestrator** with agent IDs

## Next Steps

1. **Create Knowledge Bases** for CI/CD best practices
2. **Implement GitHub API Lambda** for PR creation
3. **Add Trivy/Snyk integration** to Static Analyzer
4. **Implement Feedback Agent** log reading from GitHub API
5. **Add monitoring and observability** (CloudWatch dashboards)
6. **Implement retry logic** in orchestrator
7. **Add human-in-the-loop** approval gates

## Notes

- All agents use Claude 3.5 Sonnet by default (configurable via variable)
- Action groups are configured with DRAFT version (update after testing)
- GitHub PAT must be updated in Secrets Manager after deployment
- Lambda functions share the same deployment package for efficiency
- DynamoDB table uses pay-per-request billing mode
