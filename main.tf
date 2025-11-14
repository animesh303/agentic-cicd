# Data source to get AWS account ID
data "aws_caller_identity" "current" {}

# Local values for agent instruction hashes (to trigger updates when instructions change)
locals {
  agent_instruction_hashes = {
    repo_scanner        = sha256(aws_bedrockagent_agent.repo_scanner_agent.instruction)
    pipeline_designer   = sha256(aws_bedrockagent_agent.pipeline_designer_agent.instruction)
    security_compliance = sha256(aws_bedrockagent_agent.security_compliance_agent.instruction)
    yaml_generator      = sha256(aws_bedrockagent_agent.yaml_generator_agent.instruction)
    pr_manager          = sha256(aws_bedrockagent_agent.pr_manager_agent.instruction)
    feedback            = sha256(aws_bedrockagent_agent.feedback_agent.instruction)
  }
}

# S3 bucket to hold templates, OpenAPI spec, lambda zip
resource "aws_s3_bucket" "templates" {
  bucket        = var.bucket_name
  force_destroy = true
  tags = {
    Name = "${var.project_prefix}-templates"
  }
}

# DynamoDB table for task tracking
resource "aws_dynamodb_table" "task_tracking" {
  name         = "${var.project_prefix}-tasks"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "task_id"

  attribute {
    name = "task_id"
    type = "S"
  }

  tags = {
    Name = "${var.project_prefix}-task-tracking"
  }
}

# IAM role for Lambda functions
resource "aws_iam_role" "lambda_exec" {
  name = "${var.project_prefix}-lambda-exec"
  assume_role_policy = jsonencode({
    Version = "2012-10-17",
    Statement = [
      {
        Action    = "sts:AssumeRole",
        Principal = { Service = "lambda.amazonaws.com" },
        Effect    = "Allow",
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "lambda_basic_exec" {
  role       = aws_iam_role.lambda_exec.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# Extra permissions for Lambda functions (S3, Git access, DynamoDB, Bedrock)
resource "aws_iam_policy" "lambda_extra_policy" {
  name = "${var.project_prefix}-lambda-extra"
  policy = jsonencode({
    Version = "2012-10-17",
    Statement = [
      {
        Effect   = "Allow",
        Action   = ["s3:GetObject", "s3:PutObject", "s3:ListBucket"],
        Resource = [aws_s3_bucket.templates.arn, "${aws_s3_bucket.templates.arn}/*"]
      },
      {
        Effect   = "Allow",
        Action   = ["secretsmanager:GetSecretValue"],
        Resource = "*"
      },
      {
        Effect   = "Allow",
        Action   = ["dynamodb:PutItem", "dynamodb:GetItem", "dynamodb:UpdateItem"],
        Resource = aws_dynamodb_table.task_tracking.arn
      },
      {
        Effect = "Allow",
        Action = [
          "bedrock:InvokeModel",
          "bedrock:InvokeAgent",
          "bedrock:InvokeAgentWithResponseStream"
        ],
        Resource = [
          "arn:aws:bedrock:*:*:agent-alias/*/*",
          "arn:aws:bedrock:*:*:agent/*",
          "*"
        ]
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "lambda_extra_attach" {
  role       = aws_iam_role.lambda_exec.name
  policy_arn = aws_iam_policy.lambda_extra_policy.arn
}

# Build Lambda package with dependencies
resource "null_resource" "lambda_build" {
  triggers = {
    # Trigger rebuild when Lambda code or requirements change
    lambda_code_hash = sha256(join("", [
      for f in fileset("${path.module}/lambda", "*.py") : filesha256("${path.module}/lambda/${f}")
    ]))
    requirements_hash = filesha256("${path.module}/lambda/requirements.txt")
  }

  provisioner "local-exec" {
    command = <<-EOT
      set -e
      BUILD_DIR="${path.module}/build/lambda_package"
      LAMBDA_DIR="${path.module}/lambda"
      ZIP_FILE="${path.module}/build/lambda_functions.zip"
      BUILD_PARENT="${path.module}/build"
      
      # Ensure build directory exists
      mkdir -p "$BUILD_PARENT"
      mkdir -p "$BUILD_DIR"
      
      # Remove existing zip file if it exists
      rm -f "$ZIP_FILE"
      
      # Clean build directory
      rm -rf "$BUILD_DIR"/*
      mkdir -p "$BUILD_DIR"
      
      # Copy Lambda function files
      if ls "$LAMBDA_DIR"/*.py 1> /dev/null 2>&1; then
        cp "$LAMBDA_DIR"/*.py "$BUILD_DIR/"
      else
        echo "Warning: No Python files found in $LAMBDA_DIR"
        exit 1
      fi
      
      # Install dependencies for Linux (Lambda runtime)
      # Use --platform to ensure Linux-compatible packages are installed
      if [ -f "$LAMBDA_DIR/requirements.txt" ]; then
        echo "Installing dependencies from requirements.txt for Linux platform..."
        # Install with Linux platform target (manylinux2014_x86_64 for Python 3.11)
        pip install -r "$LAMBDA_DIR/requirements.txt" \
          -t "$BUILD_DIR" \
          --platform manylinux2014_x86_64 \
          --implementation cp \
          --python-version 3.11 \
          --only-binary=:all: \
          --upgrade \
          --quiet \
          --disable-pip-version-check || {
          echo "Warning: Platform-specific install failed, trying without platform flag..."
          # Fallback: install without platform flag (works for pure Python packages)
          pip install -r "$LAMBDA_DIR/requirements.txt" -t "$BUILD_DIR" --upgrade --quiet --disable-pip-version-check
        }
        echo "Dependencies installed. Verifying requests module..."
        if [ -d "$BUILD_DIR/requests" ] || [ -f "$BUILD_DIR/requests.py" ]; then
          echo "✓ requests module found"
        else
          echo "⚠ Warning: requests module not found in build directory"
          ls -la "$BUILD_DIR" | head -20
        fi
      else
        echo "Warning: requirements.txt not found"
      fi
      
      # Ensure zip file's parent directory exists
      ZIP_DIR=$(dirname "$ZIP_FILE")
      mkdir -p "$ZIP_DIR"
      
      # Create zip file using Python (more reliable than shell zip command)
      python3 <<PYTHON_SCRIPT
import os
import zipfile
import sys

build_dir = "$BUILD_DIR"
zip_file = "$ZIP_FILE"

if not os.path.exists(build_dir):
    print(f"Error: Build directory does not exist: {build_dir}")
    sys.exit(1)

# List what we're about to package
print("Packaging contents:")
python_files = [f for f in os.listdir(build_dir) if f.endswith('.py')]
print(f"  Python files: {len(python_files)}")
for f in python_files[:5]:  # Show first 5
    print(f"    - {f}")

# Check for key packages
key_packages = ['requests', 'yaml', 'boto3']
for pkg in key_packages:
    pkg_path = os.path.join(build_dir, pkg)
    if os.path.exists(pkg_path):
        print(f"  ✓ Found package: {pkg}")
    else:
        # Check if it's a .py file
        pkg_file = os.path.join(build_dir, f"{pkg}.py")
        if os.path.exists(pkg_file):
            print(f"  ✓ Found module: {pkg}.py")
        else:
            print(f"  ⚠ Warning: {pkg} not found")

try:
    file_count = 0
    with zipfile.ZipFile(zip_file, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(build_dir):
            # Skip __pycache__ directories
            dirs[:] = [d for d in dirs if d != '__pycache__']
            for file in files:
                # Skip .pyc files
                if file.endswith('.pyc'):
                    continue
                file_path = os.path.join(root, file)
                arcname = os.path.relpath(file_path, build_dir)
                zipf.write(file_path, arcname)
                file_count += 1
    
    print(f"Successfully created zip file: {zip_file}")
    print(f"Total files packaged: {file_count}")
    
    # Verify zip contents
    with zipfile.ZipFile(zip_file, 'r') as zipf:
        zip_contents = zipf.namelist()
        print(f"Zip file contains {len(zip_contents)} files")
        # Check for requests
        requests_files = [f for f in zip_contents if 'requests' in f]
        if requests_files:
            print(f"  ✓ Found {len(requests_files)} requests-related files")
        else:
            print("  ⚠ Warning: No requests files found in zip")
            
except Exception as e:
    print(f"Error creating zip file: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
PYTHON_SCRIPT
      
      if [ $? -ne 0 ]; then
        echo "Error: Failed to create zip file using Python"
        exit 1
      fi
      
      # Verify zip file was created
      if [ ! -f "$ZIP_FILE" ]; then
        echo "Error: Failed to create zip file at $ZIP_FILE"
        echo "Build directory contents:"
        ls -la "$BUILD_DIR" || true
        exit 1
      fi
      
      echo "Lambda package created: $ZIP_FILE"
      echo "Package size: $(du -h "$ZIP_FILE" | cut -f1)"
      
      # Clean up build directory (optional, keep for debugging)
      # rm -rf "$BUILD_DIR"
    EOT
  }
}

# Note: source_code_hash uses filebase64sha256 which reads the file after null_resource creates it

# Repository Scanner Lambda (original)
resource "aws_lambda_function" "repo_scanner" {
  filename         = "${path.module}/build/lambda_functions.zip"
  function_name    = "${var.project_prefix}-repo-scanner"
  role             = aws_iam_role.lambda_exec.arn
  handler          = "repo_scanner.lambda_handler"
  runtime          = var.lambda_runtime
  source_code_hash = filebase64sha256("${path.module}/build/lambda_functions.zip")
  timeout          = 900
  depends_on = [
    null_resource.lambda_build,
    aws_iam_role_policy_attachment.lambda_basic_exec,
    aws_iam_role_policy_attachment.lambda_extra_attach
  ]
}

# Repository Ingestor Lambda
resource "aws_lambda_function" "repo_ingestor" {
  filename         = "${path.module}/build/lambda_functions.zip"
  function_name    = "${var.project_prefix}-repo-ingestor"
  role             = aws_iam_role.lambda_exec.arn
  handler          = "repo_ingestor.lambda_handler"
  runtime          = var.lambda_runtime
  source_code_hash = filebase64sha256("${path.module}/build/lambda_functions.zip")
  timeout          = 900
  depends_on = [
    null_resource.lambda_build,
    aws_iam_role_policy_attachment.lambda_basic_exec,
    aws_iam_role_policy_attachment.lambda_extra_attach
  ]
}

# Static Analyzer Lambda
resource "aws_lambda_function" "static_analyzer" {
  filename         = "${path.module}/build/lambda_functions.zip"
  function_name    = "${var.project_prefix}-static-analyzer"
  role             = aws_iam_role.lambda_exec.arn
  handler          = "static_analyzer.lambda_handler"
  runtime          = var.lambda_runtime
  source_code_hash = filebase64sha256("${path.module}/build/lambda_functions.zip")
  timeout          = 900
  depends_on = [
    null_resource.lambda_build,
    aws_iam_role_policy_attachment.lambda_basic_exec,
    aws_iam_role_policy_attachment.lambda_extra_attach
  ]
}

# Template Validator Lambda
resource "aws_lambda_function" "template_validator" {
  filename         = "${path.module}/build/lambda_functions.zip"
  function_name    = "${var.project_prefix}-template-validator"
  role             = aws_iam_role.lambda_exec.arn
  handler          = "template_validator.lambda_handler"
  runtime          = var.lambda_runtime
  source_code_hash = filebase64sha256("${path.module}/build/lambda_functions.zip")
  timeout          = 300
  depends_on = [
    null_resource.lambda_build,
    aws_iam_role_policy_attachment.lambda_basic_exec,
    aws_iam_role_policy_attachment.lambda_extra_attach
  ]
}

# Orchestrator Lambda
resource "aws_lambda_function" "orchestrator" {
  filename         = "${path.module}/build/lambda_functions.zip"
  function_name    = "${var.project_prefix}-orchestrator"
  role             = aws_iam_role.lambda_exec.arn
  handler          = "orchestrator.lambda_handler"
  runtime          = var.lambda_runtime
  source_code_hash = filebase64sha256("${path.module}/build/lambda_functions.zip")
  timeout          = 900
  environment {
    variables = {
      TASK_TABLE_NAME               = aws_dynamodb_table.task_tracking.name
      AGENT_ALIAS_ID                = var.agent_alias_id
      STATIC_ANALYZER_FUNCTION_NAME = aws_lambda_function.static_analyzer.function_name
    }
  }
  depends_on = [
    null_resource.lambda_build,
    aws_iam_role_policy_attachment.lambda_basic_exec,
    aws_iam_role_policy_attachment.lambda_extra_attach
  ]
}

# GitHub API Lambda
resource "aws_lambda_function" "github_api" {
  filename         = "${path.module}/build/lambda_functions.zip"
  function_name    = "${var.project_prefix}-github-api"
  role             = aws_iam_role.lambda_exec.arn
  handler          = "github_api.lambda_handler"
  runtime          = var.lambda_runtime
  source_code_hash = filebase64sha256("${path.module}/build/lambda_functions.zip")
  timeout          = 300
  environment {
    variables = {
      GITHUB_PAT_SECRET_NAME = aws_secretsmanager_secret.github_pat.name
    }
  }
  depends_on = [
    null_resource.lambda_build,
    aws_iam_role_policy_attachment.lambda_basic_exec,
    aws_iam_role_policy_attachment.lambda_extra_attach
  ]
}

# Secrets Manager for GitHub PAT
resource "aws_secretsmanager_secret" "github_pat" {
  name = var.github_pat_secret_name
}

resource "aws_secretsmanager_secret_version" "github_pat_value" {
  secret_id     = aws_secretsmanager_secret.github_pat.id
  secret_string = jsonencode({ token = "REPLACE_ME_WITH_GITHUB_PAT" })
  depends_on    = [aws_secretsmanager_secret.github_pat]
}

# Bedrock Agent IAM role - allow Bedrock to call Lambda, read S3, and invoke other agents
resource "aws_iam_role" "bedrock_agent_role" {
  name = "${var.project_prefix}-bedrock-agent-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17",
    Statement = [
      {
        Effect    = "Allow",
        Principal = { Service = "bedrock.amazonaws.com" },
        Action    = "sts:AssumeRole"
      }
    ]
  })
}

resource "aws_iam_policy" "bedrock_agent_policy" {
  name = "${var.project_prefix}-bedrock-agent-policy"
  policy = jsonencode({
    Version = "2012-10-17",
    Statement = [
      {
        Effect = "Allow",
        Action = ["lambda:InvokeFunction"],
        Resource = [
          aws_lambda_function.repo_scanner.arn,
          aws_lambda_function.repo_ingestor.arn,
          aws_lambda_function.static_analyzer.arn,
          aws_lambda_function.template_validator.arn,
          aws_lambda_function.orchestrator.arn,
          aws_lambda_function.github_api.arn
        ]
      },
      {
        Effect   = "Allow",
        Action   = ["s3:GetObject", "s3:ListBucket"],
        Resource = [aws_s3_bucket.templates.arn, "${aws_s3_bucket.templates.arn}/*"]
      },
      {
        Effect   = "Allow",
        Action   = ["secretsmanager:GetSecretValue"],
        Resource = [aws_secretsmanager_secret.github_pat.arn]
      },
      {
        Effect   = "Allow",
        Action   = ["bedrock:InvokeAgent"],
        Resource = "*"
      },
      {
        Effect = "Allow",
        Action = [
          "bedrock:InvokeModel",
          "bedrock:InvokeModelWithResponseStream"
        ],
        Resource = [
          "arn:aws:bedrock:us-east-1::foundation-model/anthropic.claude-3-5-sonnet-20241022-v2:0",
          "arn:aws:bedrock:us-east-1::foundation-model/anthropic.claude-3-5-sonnet-*",
          "arn:aws:bedrock:*::foundation-model/anthropic.claude-3-5-sonnet-20241022-v2:0",
          "arn:aws:bedrock:*::foundation-model/anthropic.claude-3-5-sonnet-*",
          "arn:aws:bedrock:*::foundation-model/anthropic.claude-*",
          "arn:aws:bedrock:*::foundation-model/*",
          "arn:aws:bedrock:*:*:inference-profile/us.anthropic.claude-3-5-sonnet-*",
          "arn:aws:bedrock:*:*:inference-profile/*"
        ]
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "bedrock_agent_policy_attach" {
  role       = aws_iam_role.bedrock_agent_role.name
  policy_arn = aws_iam_policy.bedrock_agent_policy.arn
}

# ============================================================================
# BEDROCK AGENTS
# ============================================================================

# 1. Repo Scanner Agent
resource "aws_bedrockagent_agent" "repo_scanner_agent" {
  agent_name              = "${var.project_prefix}-repo-scanner-agent"
  description             = "Scans repositories and builds inventory: languages, build systems, containers, tests, infra targets"
  agent_resource_role_arn = aws_iam_role.bedrock_agent_role.arn
  foundation_model        = var.bedrock_foundation_model
  instruction             = <<EOF
You are a repository analysis expert. Your role is to analyze source repositories and identify:
- Programming languages and frameworks
- Build systems and package managers
- Dockerfiles and containerization
- Test frameworks and test files
- Infrastructure as Code (Terraform, CloudFormation, Helm, Kubernetes)
- Deployment targets (ECR, ECS, Lambda, etc.)

Return a structured JSON summary with all findings.

IMPORTANT: Do not use thinking tags or chain-of-thought reasoning. Provide direct answers only.
EOF

}

# 2. Pipeline Designer Agent
resource "aws_bedrockagent_agent" "pipeline_designer_agent" {
  agent_name              = "${var.project_prefix}-pipeline-designer-agent"
  description             = "Designs CI/CD pipeline stages: build/test/lint/scan/image, matrix strategy, cache, artifacts"
  agent_resource_role_arn = aws_iam_role.bedrock_agent_role.arn
  foundation_model        = var.bedrock_foundation_model
  instruction             = <<EOF
You are a CI/CD pipeline architect. Based on repository analysis, design a comprehensive pipeline with:
- Appropriate build stages
- Test execution strategy
- Security scanning stages (SAST, SCA, container scanning)
- Container image build and push to ECR
- Deployment steps for ECS/Fargate
- Caching strategies
- Artifact management
- Matrix builds for multiple versions/platforms if needed

Provide a detailed pipeline design specification.

IMPORTANT: Do not use thinking tags or chain-of-thought reasoning. Provide direct answers only.
EOF

}

# 3. Security & Compliance Agent
resource "aws_bedrockagent_agent" "security_compliance_agent" {
  agent_name              = "${var.project_prefix}-security-compliance-agent"
  description             = "Ensures SAST/SCA, secrets scanning, least privilege for deployment roles"
  agent_resource_role_arn = aws_iam_role.bedrock_agent_role.arn
  foundation_model        = var.bedrock_foundation_model
  instruction             = <<EOF
You are a security and compliance expert for CI/CD pipelines. Review pipeline designs and ensure:
- SAST (Static Application Security Testing) is included
- SCA (Software Composition Analysis) for dependencies
- Secrets scanning in code and containers
- Least privilege IAM permissions
- Security best practices for AWS deployments
- Compliance with organizational security policies

Provide security recommendations and compliance checks.

IMPORTANT: Do not use thinking tags or chain-of-thought reasoning. Provide direct answers only.
EOF

}

# 4. YAML Generator Agent
resource "aws_bedrockagent_agent" "yaml_generator_agent" {
  agent_name              = "${var.project_prefix}-yaml-generator-agent"
  description             = "Generates ready-to-run GitHub Actions YAML and README for maintainers"
  agent_resource_role_arn = aws_iam_role.bedrock_agent_role.arn
  foundation_model        = var.bedrock_foundation_model
  instruction             = <<EOF
You are a GitHub Actions workflow generator. Convert pipeline designs into concrete GitHub Actions YAML workflows.

Requirements:
- Use aws-actions/configure-aws-credentials for AWS authentication
- Use amazon-ecr-login for ECR authentication
- Include proper secrets management with secrets.*
- Follow GitHub Actions best practices
- Include comments explaining each stage
- Generate a README section explaining the pipeline

Return only valid YAML in a code block.

IMPORTANT: Do not use thinking tags or chain-of-thought reasoning. Provide direct answers only.
EOF

}

# 5. PR Manager Agent
resource "aws_bedrockagent_agent" "pr_manager_agent" {
  agent_name              = "${var.project_prefix}-pr-manager-agent"
  description             = "Creates PRs, populates description with rationale, test results, and required secrets/permissions"
  agent_resource_role_arn = aws_iam_role.bedrock_agent_role.arn
  foundation_model        = var.bedrock_foundation_model
  instruction             = <<EOF
You are a GitHub PR manager. Create pull requests with:
- Clear, descriptive titles (e.g., "Add CI/CD pipeline for [repo-name]")
- Comprehensive descriptions explaining:
  * What the pipeline does
  * Why each stage is included
  * Required secrets and permissions
  * How to test the pipeline
  * Deployment instructions
- Proper branch naming (e.g., "ci-cd/add-pipeline" or "feature/ci-cd-pipeline")
- IMPORTANT: Always create DRAFT PRs (draft: true) for human-in-the-loop review
- Include the generated workflow YAML file in .github/workflows/ci-cd.yml
- Add appropriate labels if needed

Use the GitHub API action group to create draft PRs with the generated workflow files.
The API expects: operation="create_pr", owner, repo, title, head (branch), base (target branch), 
draft=true, body (description), and files array with path and content.

IMPORTANT: Do not use thinking tags or chain-of-thought reasoning. Provide direct answers only.
EOF

}

# 6. Feedback Agent
resource "aws_bedrockagent_agent" "feedback_agent" {
  agent_name              = "${var.project_prefix}-feedback-agent"
  description             = "Reads CI run logs and suggests pipeline improvements automatically"
  agent_resource_role_arn = aws_iam_role.bedrock_agent_role.arn
  foundation_model        = var.bedrock_foundation_model
  instruction             = <<EOF
You are a CI/CD pipeline optimization expert. Analyze GitHub Actions run logs and suggest improvements:
- Caching optimizations
- Parallelization opportunities
- Build time reductions
- Resource optimization
- Error handling improvements
- Best practice recommendations

Provide actionable suggestions with examples.

IMPORTANT: Do not use thinking tags or chain-of-thought reasoning. Provide direct answers only.
EOF

}

# ============================================================================
# ACTION GROUPS FOR AGENTS
# ============================================================================

# Action Group: Repo Ingestor Lambda for Repo Scanner Agent
resource "aws_bedrockagent_agent_action_group" "repo_scanner_lambda_action" {
  agent_id          = aws_bedrockagent_agent.repo_scanner_agent.id
  agent_version     = "DRAFT"
  action_group_name = "repo-ingestor-action"
  description       = "Invoke repository ingestor Lambda to extract manifest files"

  action_group_executor {
    lambda = aws_lambda_function.repo_ingestor.arn
  }

  api_schema {
    s3 {
      s3_bucket_name = aws_s3_bucket.templates.id
      s3_object_key  = aws_s3_object.repo_ingestor_openapi.key
    }
  }

  # Ensure Lambda permissions are created before action group
  depends_on = [
    aws_lambda_permission.bedrock_repo_ingestor
  ]
}

# Action Group: Static Analyzer Lambda for Security Agent
resource "aws_bedrockagent_agent_action_group" "security_static_analyzer_action" {
  agent_id          = aws_bedrockagent_agent.security_compliance_agent.id
  agent_version     = "DRAFT"
  action_group_name = "static-analyzer-action"
  description       = "Invoke static analyzer Lambda for security and dependency analysis"

  action_group_executor {
    lambda = aws_lambda_function.static_analyzer.arn
  }

  api_schema {
    s3 {
      s3_bucket_name = aws_s3_bucket.templates.id
      s3_object_key  = aws_s3_object.static_analyzer_openapi.key
    }
  }

  depends_on = [
    aws_lambda_permission.bedrock_static_analyzer
  ]
}

# Action Group: Template Validator Lambda for YAML Generator Agent
resource "aws_bedrockagent_agent_action_group" "yaml_validator_action" {
  agent_id          = aws_bedrockagent_agent.yaml_generator_agent.id
  agent_version     = "DRAFT"
  action_group_name = "yaml-validator-action"
  description       = "Validate generated YAML syntax and security"

  action_group_executor {
    lambda = aws_lambda_function.template_validator.arn
  }

  api_schema {
    s3 {
      s3_bucket_name = aws_s3_bucket.templates.id
      s3_object_key  = aws_s3_object.template_validator_openapi.key
    }
  }

  depends_on = [
    aws_lambda_permission.bedrock_template_validator
  ]
}

# Action Group: GitHub API for PR Manager Agent
resource "aws_bedrockagent_agent_action_group" "pr_manager_github_action" {
  agent_id          = aws_bedrockagent_agent.pr_manager_agent.id
  agent_version     = "DRAFT"
  action_group_name = "github-api-action"
  description       = "Create GitHub PRs via API (supports draft PRs for human-in-the-loop)"

  action_group_executor {
    lambda = aws_lambda_function.github_api.arn
  }

  api_schema {
    s3 {
      s3_bucket_name = aws_s3_bucket.templates.id
      s3_object_key  = aws_s3_object.github_openapi.key
    }
  }

  depends_on = [
    aws_lambda_permission.bedrock_github_api
  ]
}

# Lambda permissions to allow Bedrock agents to invoke Lambda functions
# These permissions grant Bedrock service permission to invoke Lambda functions on behalf of agents
# Note: We don't use source_arn restriction as Bedrock may use different ARN formats when invoking
resource "aws_lambda_permission" "bedrock_repo_ingestor" {
  statement_id  = "AllowBedrockInvokeRepoIngestor"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.repo_ingestor.function_name
  principal     = "bedrock.amazonaws.com"
  # No source_arn restriction to allow Bedrock to invoke from any agent/alias
}

resource "aws_lambda_permission" "bedrock_static_analyzer" {
  statement_id  = "AllowBedrockInvokeStaticAnalyzer"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.static_analyzer.function_name
  principal     = "bedrock.amazonaws.com"
}

resource "aws_lambda_permission" "bedrock_template_validator" {
  statement_id  = "AllowBedrockInvokeTemplateValidator"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.template_validator.function_name
  principal     = "bedrock.amazonaws.com"
}

resource "aws_lambda_permission" "bedrock_github_api" {
  statement_id  = "AllowBedrockInvokeGitHubAPI"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.github_api.function_name
  principal     = "bedrock.amazonaws.com"
}

# Upload OpenAPI specs to S3
resource "aws_s3_object" "github_openapi" {
  bucket = aws_s3_bucket.templates.id
  key    = "openapi/github_pr_tool.yaml"
  source = "./openapi/github_pr_tool.yaml"
  etag   = filemd5("./openapi/github_pr_tool.yaml")
}

resource "aws_s3_object" "agent_communication_openapi" {
  bucket = aws_s3_bucket.templates.id
  key    = "openapi/agent_communication.yaml"
  source = "./openapi/agent_communication.yaml"
  etag   = filemd5("./openapi/agent_communication.yaml")
}

resource "aws_s3_object" "repo_ingestor_openapi" {
  bucket = aws_s3_bucket.templates.id
  key    = "openapi/repo_ingestor.yaml"
  source = "./openapi/repo_ingestor.yaml"
  etag   = filemd5("./openapi/repo_ingestor.yaml")
}

resource "aws_s3_object" "static_analyzer_openapi" {
  bucket = aws_s3_bucket.templates.id
  key    = "openapi/static_analyzer.yaml"
  source = "./openapi/static_analyzer.yaml"
  etag   = filemd5("./openapi/static_analyzer.yaml")
}

resource "aws_s3_object" "template_validator_openapi" {
  bucket = aws_s3_bucket.templates.id
  key    = "openapi/template_validator.yaml"
  source = "./openapi/template_validator.yaml"
  etag   = filemd5("./openapi/template_validator.yaml")
}

# Knowledge Base associations (optional - can be created separately)
# resource "aws_bedrockagent_agent_knowledge_base_association" "repo_scanner_kb" {
#   agent_id         = aws_bedrockagent_agent.repo_scanner_agent.id
#   knowledge_base_id = "REPLACE_WITH_KB_ID"
# }

# CloudWatch Log Groups for observability
resource "aws_cloudwatch_log_group" "orchestrator" {
  name              = "/aws/lambda/${aws_lambda_function.orchestrator.function_name}"
  retention_in_days = 14
}

resource "aws_cloudwatch_log_group" "github_api" {
  name              = "/aws/lambda/${aws_lambda_function.github_api.function_name}"
  retention_in_days = 14
}

resource "aws_cloudwatch_log_group" "static_analyzer" {
  name              = "/aws/lambda/${aws_lambda_function.static_analyzer.function_name}"
  retention_in_days = 14
}

resource "aws_cloudwatch_log_group" "repo_scanner" {
  name              = "/aws/lambda/${aws_lambda_function.repo_scanner.function_name}"
  retention_in_days = 14
}

resource "aws_cloudwatch_log_group" "repo_ingestor" {
  name              = "/aws/lambda/${aws_lambda_function.repo_ingestor.function_name}"
  retention_in_days = 14
}

resource "aws_cloudwatch_log_group" "template_validator" {
  name              = "/aws/lambda/${aws_lambda_function.template_validator.function_name}"
  retention_in_days = 14
}

# CloudWatch Dashboard for basic observability
resource "aws_cloudwatch_dashboard" "main" {
  dashboard_name = "${var.project_prefix}-dashboard"

  dashboard_body = jsonencode({
    widgets = [
      {
        type   = "metric"
        x      = 0
        y      = 0
        width  = 12
        height = 6
        properties = {
          metrics = [
            ["AWS/Lambda", "Invocations", "FunctionName", aws_lambda_function.orchestrator.function_name, { "stat" = "Sum", "label" = "Orchestrator" }],
            ["AWS/Lambda", "Invocations", "FunctionName", aws_lambda_function.github_api.function_name, { "stat" = "Sum", "label" = "GitHub API" }],
            ["AWS/Lambda", "Invocations", "FunctionName", aws_lambda_function.static_analyzer.function_name, { "stat" = "Sum", "label" = "Static Analyzer" }]
          ]
          view    = "timeSeries"
          stacked = false
          region  = var.aws_region
          title   = "Lambda Invocations"
          period  = 300
        }
      },
      {
        type   = "metric"
        x      = 0
        y      = 6
        width  = 12
        height = 6
        properties = {
          metrics = [
            ["AWS/Lambda", "Errors", "FunctionName", aws_lambda_function.orchestrator.function_name, { "stat" = "Sum", "label" = "Orchestrator Errors" }],
            ["AWS/Lambda", "Errors", "FunctionName", aws_lambda_function.github_api.function_name, { "stat" = "Sum", "label" = "GitHub API Errors" }],
            ["AWS/Lambda", "Errors", "FunctionName", aws_lambda_function.static_analyzer.function_name, { "stat" = "Sum", "label" = "Static Analyzer Errors" }]
          ]
          view    = "timeSeries"
          stacked = false
          region  = var.aws_region
          title   = "Lambda Errors"
          period  = 300
        }
      },
      {
        type   = "metric"
        x      = 0
        y      = 12
        width  = 12
        height = 6
        properties = {
          metrics = [
            ["AWS/Lambda", "Duration", "FunctionName", aws_lambda_function.orchestrator.function_name, { "stat" = "Average", "label" = "Orchestrator Duration" }],
            ["AWS/Lambda", "Duration", "FunctionName", aws_lambda_function.github_api.function_name, { "stat" = "Average", "label" = "GitHub API Duration" }]
          ]
          view    = "timeSeries"
          stacked = false
          region  = var.aws_region
          title   = "Lambda Duration (ms)"
          period  = 300
        }
      }
    ]
  })
}

# Prepare agents (some deployments require this step)
resource "null_resource" "prepare_agents" {
  triggers = {
    agent_ids = join(",", [
      aws_bedrockagent_agent.repo_scanner_agent.id,
      aws_bedrockagent_agent.pipeline_designer_agent.id,
      aws_bedrockagent_agent.security_compliance_agent.id,
      aws_bedrockagent_agent.yaml_generator_agent.id,
      aws_bedrockagent_agent.pr_manager_agent.id,
      aws_bedrockagent_agent.feedback_agent.id
    ])
    # Trigger on instruction changes to ensure agents are re-prepared
    instruction_hashes = join(",", [
      local.agent_instruction_hashes.repo_scanner,
      local.agent_instruction_hashes.pipeline_designer,
      local.agent_instruction_hashes.security_compliance,
      local.agent_instruction_hashes.yaml_generator,
      local.agent_instruction_hashes.pr_manager,
      local.agent_instruction_hashes.feedback
    ])
  }

  provisioner "local-exec" {
    command = <<-EOT
      aws bedrock-agent prepare-agent --agent-id ${aws_bedrockagent_agent.repo_scanner_agent.id} || true
      aws bedrock-agent prepare-agent --agent-id ${aws_bedrockagent_agent.pipeline_designer_agent.id} || true
      aws bedrock-agent prepare-agent --agent-id ${aws_bedrockagent_agent.security_compliance_agent.id} || true
      aws bedrock-agent prepare-agent --agent-id ${aws_bedrockagent_agent.yaml_generator_agent.id} || true
      aws bedrock-agent prepare-agent --agent-id ${aws_bedrockagent_agent.pr_manager_agent.id} || true
      aws bedrock-agent prepare-agent --agent-id ${aws_bedrockagent_agent.feedback_agent.id} || true
    EOT
  }
}
