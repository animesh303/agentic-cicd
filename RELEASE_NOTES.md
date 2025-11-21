# Release Notes

## Version 2.0 - November 21, 2025

### 🎉 Overview

This release represents a stable, production-ready version of the Agentic CI/CD system - a fully automated pipeline generation platform powered by Amazon Bedrock Agents. The system analyzes repositories, designs secure CI/CD pipelines, generates GitHub Actions workflows, and creates pull requests automatically.

### ✨ Key Features

#### Multi-Agent Architecture

- **6 Specialized Bedrock Agents** working in orchestrated workflows:
  - **Repo Scanner Agent**: Analyzes repository structure, identifies technologies, frameworks, and infrastructure
  - **Pipeline Designer Agent**: Designs comprehensive CI/CD pipeline stages with security scanning
  - **Security & Compliance Agent**: Ensures SAST/SCA scanning, secrets management, and least privilege IAM
  - **YAML Generator Agent**: Generates production-ready GitHub Actions workflows (CI and CD separately)
  - **PR Manager Agent**: Creates pull requests with comprehensive descriptions
  - **Feedback Agent**: Analyzes CI run logs and suggests optimizations

#### Lambda Functions

- **Orchestrator**: Coordinates all agents and manages workflow state
- **Repository Ingestor**: Clones repositories and extracts manifest files
- **Static Analyzer**: Analyzes Dockerfiles, dependencies, and test frameworks
- **Template Validator**: Validates YAML syntax and security compliance
- **GitHub API**: Handles PR creation and repository operations

#### Infrastructure

- **Terraform-managed AWS infrastructure**:
  - S3 buckets for templates and artifacts
  - DynamoDB for task tracking
  - Lambda functions with proper IAM roles
  - Bedrock Agents with action groups
  - Secrets Manager for GitHub PAT
  - CloudWatch dashboards for observability

### 🚀 What's New in v2.0

#### Improved Agent Prompts

- **Separated CI and CD workflow generation** to avoid token limits
- **Enhanced security compliance prompts** with updated best practices
- **Removed obsolete prompt files** (`yaml_generator_base.txt`, `yaml_generator_retry.txt`)
- **Centralized prompt management** with clear authoritative sources

#### Architecture Improvements

- **Dual workflow generation**: CI and CD workflows generated in separate agent calls
- **Better prompt organization**: Clear hierarchy and single source of truth for instructions
- **Enhanced documentation**: Comprehensive README for agent prompts module

#### Security Enhancements

- **Updated security scanning requirements**: Semgrep, Trivy, and Checkov integration
- **Improved OIDC authentication**: Better AWS credential management
- **Enhanced IAM validation**: Stricter least privilege checks

### 📋 System Requirements

- **AWS Account** with Bedrock access
- **Terraform** >= 1.0
- **Python** 3.11+ (for Lambda functions)
- **GitHub Personal Access Token** (stored in AWS Secrets Manager)
- **AWS CLI** configured with appropriate permissions

### 🔧 Installation & Setup

1. **Clone the repository**

   ```bash
   git clone <repository-url>
   cd agentic-cicd
   ```

2. **Configure Terraform variables**

   ```bash
   cp backend.tfvars.example backend.tfvars
   cp terraform.tfvars.example terraform.tfvars
   # Edit terraform.tfvars with your values
   ```

3. **Initialize and apply Terraform**

   ```bash
   terraform init
   terraform plan
   terraform apply
   ```

4. **Configure GitHub PAT**

   - Update the secret in AWS Secrets Manager with your GitHub Personal Access Token
   - Ensure the token has `repo` and `workflow` permissions

5. **Get agent IDs from Terraform outputs**
   ```bash
   terraform output
   ```

### 📖 Usage

#### Invoking the Orchestrator

```python
import boto3
import json

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

#### Direct Agent Invocation

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

### 🔄 Workflow

The system follows this orchestrated workflow:

1. **Repository Analysis**: Repo Scanner Agent analyzes repository structure
2. **Manifest Extraction**: Repository Ingestor Lambda extracts manifest files
3. **Static Analysis**: Static Analyzer Lambda analyzes dependencies and security
4. **Pipeline Design**: Pipeline Designer Agent creates pipeline architecture
5. **Security Review**: Security & Compliance Agent validates security requirements
6. **YAML Generation**: YAML Generator Agent creates CI and CD workflows separately
7. **Validation**: Template Validator Lambda validates YAML syntax and security
8. **PR Creation**: PR Manager Agent creates pull request with generated workflows

### 📊 Monitoring

- **CloudWatch Dashboards**: Pre-configured dashboards for Lambda invocations, errors, and duration
- **CloudWatch Logs**: All Lambda functions log to CloudWatch with 14-day retention
- **DynamoDB**: Task tracking table stores workflow state and results

### 🔐 Security Features

- **SAST Scanning**: Semgrep for static application security testing
- **SCA Scanning**: Trivy filesystem scanner for dependency vulnerabilities
- **Secrets Scanning**: Trivy secrets scanner for exposed credentials
- **IaC Scanning**: Trivy config scanner and Checkov for infrastructure security
- **Least Privilege IAM**: Validated IAM permissions follow least privilege principles
- **OIDC Authentication**: Secure AWS credential management via GitHub OIDC

### 📝 Breaking Changes

- **Removed obsolete prompt files**: `yaml_generator_base.txt` and `yaml_generator_retry.txt` are no longer used
- **Dual workflow generation**: CI and CD workflows are now generated in separate agent calls (previously combined)

### 🐛 Known Issues

- GitHub PAT must be manually updated in Secrets Manager after deployment
- Action groups use DRAFT version (update to production version after testing)
- Lambda functions share deployment package (changes to one require rebuilding all)

### 🔮 Future Enhancements

- Knowledge Base integration for CI/CD best practices
- Trivy/Snyk direct integration in Static Analyzer
- Feedback Agent log reading from GitHub API
- Human-in-the-loop approval gates
- Enhanced retry logic in orchestrator
- Multi-region deployment support

### 📚 Documentation

- [Architecture Documentation](./docs/ARCHITECTURE.md)
- [Project Overview](./docs/PROJECT.md)
- [Requirements](./docs/REQUIREMENTS.md)
- [Backend Setup](./docs/BACKEND_SETUP.md)
- [GitHub PAT Setup](./docs/GITHUB_PAT_SETUP.md)
- [ECR Terraform Handling](./docs/ECR_TERRAFORM_HANDLING.md)

### 👥 Contributing

This is an internal project. For contributions, please follow the existing code structure and update documentation accordingly.

### 📄 License

[Specify your license here]

### 🙏 Acknowledgments

Built with Amazon Bedrock Agents, AWS Lambda, and Terraform.

---

**Release Date**: November 21, 2025  
**Version**: 2.0  
**Status**: Stable (GOLD)
