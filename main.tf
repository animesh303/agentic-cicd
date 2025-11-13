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

# Lambda function zip files
data "archive_file" "lambda_zip" {
  type        = "zip"
  source_dir  = "./lambda"
  output_path = "./build/lambda_functions.zip"
  excludes    = ["__pycache__", "*.pyc", ".git"]
}

# Repository Scanner Lambda (original)
resource "aws_lambda_function" "repo_scanner" {
  filename         = data.archive_file.lambda_zip.output_path
  function_name    = "${var.project_prefix}-repo-scanner"
  role             = aws_iam_role.lambda_exec.arn
  handler          = "repo_scanner.lambda_handler"
  runtime          = var.lambda_runtime
  source_code_hash = data.archive_file.lambda_zip.output_base64sha256
  timeout          = 900
  depends_on       = [aws_iam_role_policy_attachment.lambda_basic_exec, aws_iam_role_policy_attachment.lambda_extra_attach]
}

# Repository Ingestor Lambda
resource "aws_lambda_function" "repo_ingestor" {
  filename         = data.archive_file.lambda_zip.output_path
  function_name    = "${var.project_prefix}-repo-ingestor"
  role             = aws_iam_role.lambda_exec.arn
  handler          = "repo_ingestor.lambda_handler"
  runtime          = var.lambda_runtime
  source_code_hash = data.archive_file.lambda_zip.output_base64sha256
  timeout          = 900
  depends_on       = [aws_iam_role_policy_attachment.lambda_basic_exec, aws_iam_role_policy_attachment.lambda_extra_attach]
}

# Static Analyzer Lambda
resource "aws_lambda_function" "static_analyzer" {
  filename         = data.archive_file.lambda_zip.output_path
  function_name    = "${var.project_prefix}-static-analyzer"
  role             = aws_iam_role.lambda_exec.arn
  handler          = "static_analyzer.lambda_handler"
  runtime          = var.lambda_runtime
  source_code_hash = data.archive_file.lambda_zip.output_base64sha256
  timeout          = 900
  depends_on       = [aws_iam_role_policy_attachment.lambda_basic_exec, aws_iam_role_policy_attachment.lambda_extra_attach]
}

# Template Validator Lambda
resource "aws_lambda_function" "template_validator" {
  filename         = data.archive_file.lambda_zip.output_path
  function_name    = "${var.project_prefix}-template-validator"
  role             = aws_iam_role.lambda_exec.arn
  handler          = "template_validator.lambda_handler"
  runtime          = var.lambda_runtime
  source_code_hash = data.archive_file.lambda_zip.output_base64sha256
  timeout          = 300
  depends_on       = [aws_iam_role_policy_attachment.lambda_basic_exec, aws_iam_role_policy_attachment.lambda_extra_attach]
}

# Orchestrator Lambda
resource "aws_lambda_function" "orchestrator" {
  filename         = data.archive_file.lambda_zip.output_path
  function_name    = "${var.project_prefix}-orchestrator"
  role             = aws_iam_role.lambda_exec.arn
  handler          = "orchestrator.lambda_handler"
  runtime          = var.lambda_runtime
  source_code_hash = data.archive_file.lambda_zip.output_base64sha256
  timeout          = 900
  environment {
    variables = {
      TASK_TABLE_NAME               = aws_dynamodb_table.task_tracking.name
      AGENT_ALIAS_ID                = var.agent_alias_id
      STATIC_ANALYZER_FUNCTION_NAME = aws_lambda_function.static_analyzer.function_name
    }
  }
  depends_on = [aws_iam_role_policy_attachment.lambda_basic_exec, aws_iam_role_policy_attachment.lambda_extra_attach]
}

# GitHub API Lambda
resource "aws_lambda_function" "github_api" {
  filename         = data.archive_file.lambda_zip.output_path
  function_name    = "${var.project_prefix}-github-api"
  role             = aws_iam_role.lambda_exec.arn
  handler          = "github_api.lambda_handler"
  runtime          = var.lambda_runtime
  source_code_hash = data.archive_file.lambda_zip.output_base64sha256
  timeout          = 300
  environment {
    variables = {
      GITHUB_PAT_SECRET_NAME = aws_secretsmanager_secret.github_pat.name
    }
  }
  depends_on = [aws_iam_role_policy_attachment.lambda_basic_exec, aws_iam_role_policy_attachment.lambda_extra_attach]
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
