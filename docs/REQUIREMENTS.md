# Requirements Document

## Amazon Bedrock Agentic CI/CD Pipeline Generator

**Document Version:** 1.0  
**Date:** 2024  
**Based on:** Implementation Analysis

---

## Executive Summary

This document captures the functional and non-functional requirements as implemented in the Amazon Bedrock Agentic CI/CD Pipeline Generator solution. The system automates the generation of GitHub Actions CI/CD pipelines by analyzing repositories, designing pipelines, and creating pull requests with generated workflows.

---

## 1. Functional Requirements

### 1.1 Repository Analysis

**FR-1.1.1: Repository Ingestion**

- **Requirement:** The system MUST be able to download and analyze GitHub repositories
- **Implementation:**
  - Lambda function `repo_ingestor` downloads repositories as ZIP files (no git required)
  - Supports public repositories via GitHub archive URLs
  - Handles branch fallback (main/master)
  - Extracts manifest files without requiring git clone

**FR-1.1.2: Manifest File Extraction**

- **Requirement:** The system MUST extract and return structured manifest files
- **Supported Manifest Types:**
  - Dockerfiles (all variants)
  - Package manifests: `package.json`, `requirements.txt`, `pom.xml`, `build.gradle`, `go.mod`, `Cargo.toml`
  - Infrastructure as Code: Terraform (`.tf`, `.tf.json`), CloudFormation (`.yaml`, `.yml`)
  - Kubernetes manifests (`.yaml`, `.yml` with `apiVersion` and `kind`)
  - Helm charts (`Chart.yaml`, `values.yaml`)
- **Output Format:** JSON with categorized manifest content

**FR-1.1.3: Repository Scanning**

- **Requirement:** The system MUST identify repository characteristics
- **Detected Elements:**
  - Programming languages (Python, Node.js, Java, Go, Rust)
  - Build systems and package managers
  - Containerization (Dockerfiles)
  - Infrastructure as Code (Terraform, CloudFormation)
  - Deployment targets (ECR, ECS, Lambda)

### 1.2 Static Analysis

**FR-1.2.1: Dockerfile Analysis**

- **Requirement:** The system MUST analyze Dockerfiles for best practices and security issues
- **Checks Performed:**
  - Root user usage detection
  - Potential secret exposure detection
  - Latest tag usage warnings
  - Multi-stage build detection
- **Output:** Issues list with severity levels (high, medium, low)

**FR-1.2.2: Dependency Analysis**

- **Requirement:** The system MUST analyze dependency manifest files
- **Supported Formats:**
  - `package.json` (Node.js)
  - `requirements.txt` (Python)
  - `pom.xml` (Maven/Java)
- **Output:** List of dependencies and detected test frameworks

**FR-1.2.3: Test Framework Detection**

- **Requirement:** The system MUST identify test frameworks and test files
- **Detection Methods:**
  - Directory name patterns (`test`, `spec`, `__tests__`)
  - File name patterns (`*test*`, `*spec*`)
  - Dependency analysis for test frameworks (Jest, Mocha, pytest, JUnit, etc.)

**FR-1.2.4: Vulnerability Scanning Foundation**

- **Requirement:** The system MUST provide foundation for vulnerability scanning
- **Status:** Framework in place, requires Trivy/Snyk integration (not yet implemented)

### 1.3 CI/CD Pipeline Design

**FR-1.3.1: Pipeline Design Generation**

- **Requirement:** The system MUST design CI/CD pipelines based on repository analysis
- **Design Elements:**
  - Build stages appropriate for detected languages/frameworks
  - Test execution strategy
  - Security scanning stages (SAST, SCA, container scanning)
  - Container image build and push to ECR
  - Deployment steps for ECS/Fargate
  - Caching strategies
  - Artifact management
  - Matrix builds for multiple versions/platforms (if needed)

**FR-1.3.2: Security & Compliance Review**

- **Requirement:** The system MUST review pipeline designs for security and compliance
- **Review Criteria:**
  - SAST (Static Application Security Testing) inclusion
  - SCA (Software Composition Analysis) for dependencies
  - Secrets scanning in code and containers
  - Least privilege IAM permissions
  - Security best practices for AWS deployments
  - Compliance with organizational security policies

### 1.4 YAML Generation

**FR-1.4.1: GitHub Actions YAML Generation**

- **Requirement:** The system MUST generate valid GitHub Actions workflow YAML
- **Required Elements:**
  - Workflow name
  - Trigger configuration (`on`)
  - Job definitions with `runs-on`
  - Step definitions with `uses` or `run`
  - AWS credentials configuration using `aws-actions/configure-aws-credentials`
  - ECR login using `amazon-ecr-login`
  - Proper secrets management with `secrets.*`
  - Comments explaining each stage
  - README section explaining the pipeline

**FR-1.4.2: YAML Validation**

- **Requirement:** The system MUST validate generated YAML before use
- **Validation Levels:**
  - **Strict:** No errors or warnings allowed
  - **Normal:** No errors allowed (default)
  - **Lenient:** Errors allowed
- **Validation Checks:**
  - YAML syntax validation
  - GitHub Actions structure validation
  - Security checks (hardcoded secrets detection)
  - Secrets usage validation
  - IAM permissions validation (least privilege)

### 1.5 Pull Request Management

**FR-1.5.1: Branch Creation**

- **Requirement:** The system MUST create branches for PRs
- **Functionality:**
  - Create new branch from base branch (main/master)
  - Handle existing branch scenarios (422 status code)

**FR-1.5.2: File Creation/Update**

- **Requirement:** The system MUST create or update files in repository
- **Functionality:**
  - Create new files
  - Update existing files (using SHA)
  - Support base64 encoding for content
  - Custom commit messages

**FR-1.5.3: Draft PR Creation**

- **Requirement:** The system MUST create draft pull requests for human-in-the-loop review
- **PR Elements:**
  - Descriptive title (e.g., "Add CI/CD pipeline for [repo-name]")
  - Comprehensive description including:
    - What the pipeline does
    - Why each stage is included
    - Required secrets and permissions
    - How to test the pipeline
    - Deployment instructions
  - Proper branch naming (e.g., "ci-cd/add-pipeline")
  - Draft status (default: `true`)
  - Workflow file in `.github/workflows/ci-cd.yml`

### 1.6 Orchestration

**FR-1.6.1: Workflow Orchestration**

- **Requirement:** The system MUST coordinate multi-agent workflow execution
- **Workflow Steps:**
  1. Repository Scanner Agent (analyzes repository)
  2. Static Analyzer Lambda (direct invocation)
  3. Pipeline Designer Agent (designs pipeline)
  4. Security & Compliance Agent (reviews design)
  5. YAML Generator Agent (generates YAML)
  6. Template Validator Lambda (validates YAML)
  7. PR Manager Agent (creates PR)

**FR-1.6.2: Task Tracking**

- **Requirement:** The system MUST track workflow execution state
- **Tracking Elements:**
  - Task ID (unique identifier)
  - Repository URL
  - Status (in_progress, completed, failed)
  - Timestamps (created_at, updated_at)
  - Workflow step results
  - Error information

**FR-1.6.3: Error Handling**

- **Requirement:** The system MUST handle errors gracefully
- **Error Handling:**
  - Step-level error detection
  - Task status updates on failure
  - Error messages in response
  - Workflow continuation on non-critical failures

---

## 2. Non-Functional Requirements

### 2.1 Performance

**NFR-2.1.1: Lambda Timeout**

- **Requirement:** Lambda functions MUST complete within timeout limits
- **Timeouts:**
  - Repository operations: 900 seconds (15 minutes)
  - Template validation: 300 seconds (5 minutes)
  - GitHub API operations: 300 seconds (5 minutes)

**NFR-2.1.2: Bedrock Agent Response**

- **Requirement:** Bedrock agent invocations MUST handle streaming responses
- **Implementation:**
  - 120-second read timeout
  - 10-second connect timeout
  - 3 retry attempts for transient failures

### 2.2 Scalability

**NFR-2.2.1: DynamoDB Scaling**

- **Requirement:** Task tracking MUST scale automatically
- **Implementation:** Pay-per-request billing mode (on-demand)

**NFR-2.2.2: Lambda Concurrency**

- **Requirement:** System MUST handle concurrent workflow executions
- **Implementation:** AWS Lambda default concurrency model

### 2.3 Reliability

**NFR-2.3.1: Retry Logic**

- **Requirement:** System MUST retry transient failures
- **Implementation:**
  - Bedrock client: 3 retry attempts with standard mode
  - Lambda invocations: AWS SDK default retry behavior

**NFR-2.3.2: Error Recovery**

- **Requirement:** System MUST track and report errors
- **Implementation:**
  - DynamoDB task status tracking
  - CloudWatch logging
  - Error details in response

### 2.4 Observability

**NFR-2.4.1: CloudWatch Logging**

- **Requirement:** All Lambda functions MUST log to CloudWatch
- **Log Groups:**
  - `/aws/lambda/{function-name}`
  - 14-day retention period

**NFR-2.4.2: CloudWatch Dashboard**

- **Requirement:** System MUST provide monitoring dashboard
- **Metrics Tracked:**
  - Lambda invocations (count)
  - Lambda errors (count)
  - Lambda duration (average)

**NFR-2.4.3: Bedrock Agent Tracing**

- **Requirement:** System MUST log Bedrock agent trace information
- **Trace Elements:**
  - Agent actions
  - Action group invocations
  - Response chunks

---

## 3. System Architecture Requirements

### 3.1 AWS Services

**AR-3.1.1: Amazon Bedrock Agents**

- **Requirement:** System MUST use Amazon Bedrock Agents for AI orchestration
- **Agents:**
  1. Repo Scanner Agent
  2. Pipeline Designer Agent
  3. Security & Compliance Agent
  4. YAML Generator Agent
  5. PR Manager Agent
  6. Feedback Agent (defined but not actively used in orchestrator)

**AR-3.1.2: Foundation Model**

- **Requirement:** Agents MUST use specified foundation model
- **Default:** `us.anthropic.claude-3-5-sonnet-20241022-v2:0`
- **Configurable:** Via Terraform variable

**AR-3.1.3: Agent Instructions**

- **Requirement:** Agents MUST have specialized instructions
- **Constraint:** Instructions explicitly prohibit thinking tags and chain-of-thought reasoning

### 3.2 Lambda Functions

**AR-3.2.1: Lambda Function Set**

- **Requirement:** System MUST provide the following Lambda functions:
  1. `repo_scanner` - Basic repository scanning (backward compatibility)
  2. `repo_ingestor` - Enhanced repository ingestion
  3. `static_analyzer` - Security and dependency analysis
  4. `template_validator` - YAML validation
  5. `orchestrator` - Workflow coordination
  6. `github_api` - GitHub API operations

**AR-3.2.2: Lambda Runtime**

- **Requirement:** Lambda functions MUST use Python 3.11 runtime
- **Configurable:** Via Terraform variable

**AR-3.2.3: Lambda Deployment**

- **Requirement:** Lambda functions MUST be packaged with dependencies
- **Implementation:**
  - Single deployment package (`lambda_functions.zip`)
  - Dependencies installed for Linux (Lambda runtime)
  - Platform-specific installation (manylinux2014_x86_64)

### 3.3 Storage

**AR-3.3.1: S3 Bucket**

- **Requirement:** System MUST use S3 for template and OpenAPI spec storage
- **Contents:**
  - OpenAPI specifications for action groups
  - CI/CD templates (future use)
  - Lambda deployment packages

**AR-3.3.2: DynamoDB Table**

- **Requirement:** System MUST use DynamoDB for task tracking
- **Schema:**
  - Primary Key: `task_id` (String)
  - Attributes: `repo_url`, `status`, `created_at`, `updated_at`, `result`

### 3.4 Security

**AR-3.4.1: Secrets Management**

- **Requirement:** System MUST store GitHub PAT in AWS Secrets Manager
- **Secret Name:** Configurable via Terraform variable
- **Default Value:** Placeholder ("REPLACE_ME_WITH_GITHUB_PAT")

**AR-3.4.2: IAM Roles**

- **Requirement:** System MUST use least privilege IAM roles
- **Roles:**
  - Lambda execution role
  - Bedrock agent role
- **Permissions:**
  - Lambda: S3, Secrets Manager, DynamoDB, Bedrock, Lambda invoke
  - Bedrock Agent: Lambda invoke, S3 read, Secrets Manager read, Bedrock invoke

---

## 4. Integration Requirements

### 4.1 GitHub Integration

**IR-4.1.1: GitHub API**

- **Requirement:** System MUST integrate with GitHub API
- **Operations:**
  - Repository download (ZIP archive)
  - Branch creation
  - File creation/update
  - Pull request creation
- **Authentication:** GitHub Personal Access Token (PAT) with `repo` permissions

**IR-4.1.2: Repository Access**

- **Requirement:** System MUST support public repositories
- **Limitation:** Private repositories require authentication (PAT must have access)

### 4.2 Bedrock Integration

**IR-4.2.1: Action Groups**

- **Requirement:** Agents MUST use action groups for Lambda invocation
- **Action Groups:**
  - Repo Scanner Agent → Repo Ingestor Lambda
  - Security Agent → Static Analyzer Lambda
  - YAML Generator Agent → Template Validator Lambda
  - PR Manager Agent → GitHub API Lambda

**IR-4.2.2: OpenAPI Specifications**

- **Requirement:** Action groups MUST use OpenAPI 3.0.1 specifications
- **Specifications:**
  - `github_pr_tool.yaml`
  - `repo_ingestor.yaml`
  - `static_analyzer.yaml`
  - `template_validator.yaml`

**IR-4.2.3: Agent Invocation**

- **Requirement:** Orchestrator MUST invoke agents via Bedrock Runtime API
- **Method:** `invoke_agent` with streaming response handling

---

## 5. Security Requirements

### 5.1 Authentication & Authorization

**SR-5.1.1: GitHub Authentication**

- **Requirement:** System MUST authenticate with GitHub using PAT
- **Storage:** AWS Secrets Manager
- **Access:** Lambda functions retrieve via IAM permissions

**SR-5.1.2: AWS IAM**

- **Requirement:** System MUST use IAM roles for AWS service access
- **Principle:** Least privilege access

### 5.2 Data Security

**SR-5.2.1: Secrets Handling**

- **Requirement:** System MUST NOT hardcode secrets
- **Validation:** Template validator checks for hardcoded secrets in YAML

**SR-5.2.2: Secret Scanning**

- **Requirement:** System MUST detect potential secret exposure
- **Implementation:** Dockerfile analysis and YAML validation

### 5.3 Compliance

**SR-5.3.1: Least Privilege IAM**

- **Requirement:** Generated pipelines MUST use least privilege IAM permissions
- **Validation:** Template validator checks IAM permissions in YAML

**SR-5.3.2: Security Scanning**

- **Requirement:** Generated pipelines MUST include security scanning stages
- **Required:** SAST, SCA, container scanning

---

## 6. Operational Requirements

### 6.1 Deployment

**OR-6.1.1: Infrastructure as Code**

- **Requirement:** System MUST be deployed via Terraform
- **Prerequisites:**
  - Terraform v1.5+
  - AWS CLI configured
  - Bedrock service enabled
  - S3 backend for state (optional)

**OR-6.1.2: Configuration**

- **Requirement:** System MUST be configurable via Terraform variables
- **Variables:**
  - AWS region
  - Project prefix
  - Bucket name
  - GitHub PAT secret name
  - Foundation model identifier
  - Agent alias ID

### 6.2 Maintenance

**OR-6.2.1: Agent Preparation**

- **Requirement:** Agents MUST be prepared after deployment
- **Implementation:** `null_resource` with local-exec provisioner

**OR-6.2.2: GitHub PAT Update**

- **Requirement:** GitHub PAT MUST be updated after deployment
- **Method:** Manual update in Secrets Manager (placeholder initially)

### 6.3 Validation

**OR-6.3.1: Validation Script**

- **Requirement:** System MUST provide validation script
- **Location:** `scripts/validate.sh`

**OR-6.3.2: Validation Documentation**

- **Requirement:** System MUST provide validation documentation
- **Location:** `docs/VALIDATION.md`

---

## 7. Limitations & Known Issues

### 7.1 Current Limitations

**LIM-7.1.1: Vulnerability Scanning**

- **Status:** Framework in place, not fully implemented
- **Note:** Requires Trivy/Snyk integration

**LIM-7.1.2: Private Repositories**

- **Status:** Supports public repositories
- **Note:** Private repositories require PAT with appropriate permissions

**LIM-7.1.3: Feedback Agent**

- **Status:** Defined but not actively used in orchestrator workflow
- **Note:** Intended for future CI run log analysis

**LIM-7.1.4: Knowledge Bases**

- **Status:** Not implemented
- **Note:** Terraform includes commented-out knowledge base association

**LIM-7.1.5: Agent Memory**

- **Status:** Not configured
- **Note:** Optional feature for remembering patterns

### 7.2 Technical Constraints

**LIM-7.2.1: Git Dependency**

- **Status:** `repo_scanner` Lambda uses git clone
- **Note:** `repo_ingestor` uses ZIP download (no git required)

**LIM-7.2.2: Branch Fallback**

- **Status:** Limited to main/master branches
- **Note:** Does not enumerate all branches

**LIM-7.2.3: Action Group Version**

- **Status:** Uses DRAFT version
- **Note:** Should be updated to production version after testing

---

## 8. Future Enhancements

### 8.1 Planned Features

**FE-8.1.1: Knowledge Base Integration**

- Create Bedrock Knowledge Bases for CI/CD best practices
- Attach to agents for improved accuracy

**FE-8.1.2: Trivy/Snyk Integration**

- Integrate vulnerability scanning tools
- Add to static analyzer Lambda

**FE-8.1.3: Feedback Agent Implementation**

- Implement CI run log reading from GitHub API
- Provide optimization suggestions

**FE-8.1.4: Monitoring & Observability**

- Enhanced CloudWatch dashboards
- Custom metrics and alarms

**FE-8.1.5: Retry Logic**

- Implement retry logic in orchestrator
- Handle transient failures gracefully

**FE-8.1.6: Human-in-the-Loop**

- Add approval gates
- Integration with notification systems

---

## 9. Requirements Traceability

### 9.1 Functional Requirements Coverage

| Requirement ID | Status         | Implementation                        |
| -------------- | -------------- | ------------------------------------- |
| FR-1.1.1       | ✅ Implemented | `repo_ingestor.py`                    |
| FR-1.1.2       | ✅ Implemented | `repo_ingestor.py`                    |
| FR-1.1.3       | ✅ Implemented | `repo_scanner.py`, `repo_ingestor.py` |
| FR-1.2.1       | ✅ Implemented | `static_analyzer.py`                  |
| FR-1.2.2       | ✅ Implemented | `static_analyzer.py`                  |
| FR-1.2.3       | ✅ Implemented | `static_analyzer.py`                  |
| FR-1.2.4       | ⚠️ Partial     | Framework exists, needs integration   |
| FR-1.3.1       | ✅ Implemented | Pipeline Designer Agent               |
| FR-1.3.2       | ✅ Implemented | Security & Compliance Agent           |
| FR-1.4.1       | ✅ Implemented | YAML Generator Agent                  |
| FR-1.4.2       | ✅ Implemented | `template_validator.py`               |
| FR-1.5.1       | ✅ Implemented | `github_api.py`                       |
| FR-1.5.2       | ✅ Implemented | `github_api.py`                       |
| FR-1.5.3       | ✅ Implemented | `github_api.py`, PR Manager Agent     |
| FR-1.6.1       | ✅ Implemented | `orchestrator.py`                     |
| FR-1.6.2       | ✅ Implemented | DynamoDB + `orchestrator.py`          |
| FR-1.6.3       | ✅ Implemented | `orchestrator.py`                     |

### 9.2 Non-Functional Requirements Coverage

| Requirement ID | Status         | Implementation                 |
| -------------- | -------------- | ------------------------------ |
| NFR-2.1.1      | ✅ Implemented | Lambda timeout configuration   |
| NFR-2.1.2      | ✅ Implemented | Bedrock client configuration   |
| NFR-2.2.1      | ✅ Implemented | DynamoDB on-demand billing     |
| NFR-2.2.2      | ✅ Implemented | AWS Lambda default concurrency |
| NFR-2.3.1      | ✅ Implemented | Bedrock retry configuration    |
| NFR-2.3.2      | ✅ Implemented | Error tracking in DynamoDB     |
| NFR-2.4.1      | ✅ Implemented | CloudWatch log groups          |
| NFR-2.4.2      | ✅ Implemented | CloudWatch dashboard           |
| NFR-2.4.3      | ✅ Implemented | Bedrock trace logging          |

---

## 10. Conclusion

This requirements document captures the implemented functionality of the Amazon Bedrock Agentic CI/CD Pipeline Generator. The system provides:

✅ **Core Functionality:**

- Repository analysis and manifest extraction
- Static analysis (Dockerfiles, dependencies, tests)
- CI/CD pipeline design and generation
- GitHub Actions YAML generation and validation
- Draft PR creation with comprehensive descriptions

✅ **Architecture:**

- Multi-agent Bedrock architecture
- Lambda-based processing
- DynamoDB task tracking
- S3 storage for templates and specs

✅ **Security:**

- Secrets management via AWS Secrets Manager
- Least privilege IAM roles
- Security scanning in generated pipelines

⚠️ **Areas for Enhancement:**

- Vulnerability scanning integration (Trivy/Snyk)
- Knowledge base integration
- Feedback agent implementation
- Enhanced monitoring

The solution provides a solid foundation for automated CI/CD pipeline generation with room for future enhancements as identified in Section 8.

---

**Document End**
