#!/usr/bin/env python3
"""
Orchestrator/Controller Lambda
Coordinates agents and tracks tasks. Manages the workflow between different agents.
"""
import json
import re
import boto3
import os
from datetime import datetime
from botocore.config import Config
from agent_prompts.prompt_loader import format_prompt

# Initialize clients - AWS_REGION is automatically set by Lambda runtime
# Use explicit region to ensure consistency with Bedrock agents
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")

# Configure boto3 client with explicit timeouts to prevent hanging connections
# read_timeout: Maximum time to wait for response data (120 seconds)
# connect_timeout: Maximum time to establish connection (10 seconds)
# max_retries: Number of retry attempts for transient failures
BEDROCK_CONFIG = Config(
    read_timeout=120,  # 2 minutes for reading streaming response
    connect_timeout=10,  # 10 seconds to establish connection
    retries={"max_attempts": 3, "mode": "standard"},
)

bedrock_agent_runtime = boto3.client(
    "bedrock-agent-runtime", region_name=AWS_REGION, config=BEDROCK_CONFIG
)
lambda_client = boto3.client("lambda", region_name=AWS_REGION)
dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)

# Initialize DynamoDB table for task tracking (create separately in Terraform)
TASK_TABLE_NAME = os.environ.get("TASK_TABLE_NAME", "agentic-cicd-tasks")
AGENT_ALIAS_ID = os.environ.get("AGENT_ALIAS_ID", "TSTALIASID")
REPO_INGESTOR_FUNCTION_NAME = os.environ.get("REPO_INGESTOR_FUNCTION_NAME")
STATIC_ANALYZER_FUNCTION_NAME = os.environ.get("STATIC_ANALYZER_FUNCTION_NAME")
TEMPLATE_VALIDATOR_FUNCTION_NAME = os.environ.get("TEMPLATE_VALIDATOR_FUNCTION_NAME")
GITHUB_API_FUNCTION_NAME = os.environ.get("GITHUB_API_FUNCTION_NAME")


def create_task_record(task_id, repo_url, status="in_progress"):
    """Create or update task record in DynamoDB"""
    try:
        table = dynamodb.Table(TASK_TABLE_NAME)
        table.put_item(
            Item={
                "task_id": task_id,
                "repo_url": repo_url,
                "status": status,
                "created_at": datetime.utcnow().isoformat(),
                "updated_at": datetime.utcnow().isoformat(),
            }
        )
    except Exception as e:
        # Table might not exist, log but continue
        print(f"Warning: Could not write to DynamoDB: {e}")


def update_task_status(task_id, status, result=None):
    """Update task status in DynamoDB"""
    try:
        table = dynamodb.Table(TASK_TABLE_NAME)
        update_expr = "SET #status = :status, updated_at = :updated"
        expr_attrs = {":status": status, ":updated": datetime.utcnow().isoformat()}
        expr_names = {"#status": "status"}

        if result:
            update_expr += ", #result = :result"
            expr_attrs[":result"] = json.dumps(result)
            expr_names["#result"] = "result"

        table.update_item(
            Key={"task_id": task_id},
            UpdateExpression=update_expr,
            ExpressionAttributeNames=expr_names,
            ExpressionAttributeValues=expr_attrs,
        )
    except Exception as e:
        print(f"Warning: Could not update DynamoDB: {e}")


def invoke_agent(agent_id, agent_alias_id, session_id, input_text, max_retries=2):
    """Invoke a Bedrock agent with timeout handling and retry logic"""
    import time

    for attempt in range(max_retries + 1):
        try:
            if attempt > 0:
                wait_time = 2**attempt  # Exponential backoff: 2s, 4s
                print(
                    f"Retrying agent {agent_id} (attempt {attempt + 1}/{max_retries + 1}) after {wait_time}s..."
                )
                time.sleep(wait_time)
                # Use a new session ID for retry to avoid conflicts
                session_id = f"{session_id}-retry-{attempt}"

            print(f"Invoking agent {agent_id} with session {session_id}")
            response = bedrock_agent_runtime.invoke_agent(
                agentId=agent_id,
                agentAliasId=agent_alias_id,
                sessionId=session_id,
                inputText=input_text,
            )

            # Read streaming response
            completion = ""
            chunk_count = 0
            action_group_invocations = []
            for event in response["completion"]:
                if "chunk" in event:
                    chunk = event["chunk"]
                    if "bytes" in chunk:
                        completion += chunk["bytes"].decode("utf-8")
                        chunk_count += 1
                elif "trace" in event:
                    # Log trace information for debugging
                    trace = event["trace"]
                    if "tracePart" in trace:
                        trace_part = trace["tracePart"]
                        if "agent" in trace_part:
                            agent_info = trace_part.get("agent", {})
                            action = agent_info.get("action", "unknown")
                            print(f"Agent trace - action: {action}")

                            # Capture action group invocations
                            if "actionGroupInvocationInput" in trace_part:
                                invocation = trace_part["actionGroupInvocationInput"]
                                api_path = invocation.get("apiPath", "unknown")
                                http_method = invocation.get("httpMethod", "unknown")
                                print(
                                    f"  → Action Group Invocation: {http_method} {api_path}"
                                )
                                action_group_invocations.append(
                                    {
                                        "api_path": api_path,
                                        "http_method": http_method,
                                        "action_group": invocation.get(
                                            "actionGroupName", "unknown"
                                        ),
                                    }
                                )

                            # Capture action group responses
                            if "actionGroupInvocationOutput" in trace_part:
                                output = trace_part["actionGroupInvocationOutput"]
                                http_status = output.get("httpStatusCode", "unknown")
                                print(f"  ← Action Group Response: HTTP {http_status}")

                            # Capture observation (agent's understanding)
                            if "observation" in trace_part:
                                observation = trace_part["observation"]
                                if "actionGroupInvocationOutput" in observation:
                                    output = observation["actionGroupInvocationOutput"]
                                    http_status = output.get(
                                        "httpStatusCode", "unknown"
                                    )
                                    print(f"  ← Observation: HTTP {http_status}")

            print(
                f"Agent {agent_id} completed with {chunk_count} chunks, response length: {len(completion)}"
            )
            if action_group_invocations:
                print(f"Action group invocations: {len(action_group_invocations)}")
                for inv in action_group_invocations:
                    print(
                        f"  - {inv['http_method']} {inv['api_path']} ({inv['action_group']})"
                    )
            return {
                "status": "success",
                "completion": completion,
                "action_group_invocations": action_group_invocations,
            }
        except Exception as e:
            error_msg = str(e)
            error_type = type(e).__name__

            # Check if this is a retryable error
            is_retryable = (
                "dependencyFailedException" in error_msg
                or "ThrottlingException" in error_type
                or "ServiceException" in error_type
                or "InternalServerException" in error_type
            )

            if is_retryable and attempt < max_retries:
                print(
                    f"Retryable error invoking agent {agent_id} (type: {error_type}): {error_msg}"
                )
                continue  # Retry
            else:
                # Not retryable or max retries reached
                print(
                    f"Error invoking agent {agent_id} (type: {error_type}): {error_msg}"
                )
                import traceback

                print(f"Traceback: {traceback.format_exc()}")
                return {
                    "status": "error",
                    "message": error_msg,
                    "error_type": error_type,
                }

    # Should not reach here, but just in case
    return {
        "status": "error",
        "message": "Max retries exceeded",
        "error_type": "MaxRetriesExceeded",
    }


def invoke_lambda(function_name, payload):
    """Invoke a Lambda function synchronously"""
    try:
        response = lambda_client.invoke(
            FunctionName=function_name,
            InvocationType="RequestResponse",
            Payload=json.dumps(payload),
        )

        result = json.loads(response["Payload"].read())
        return result
    except Exception as e:
        print(f"Error invoking Lambda {function_name}: {str(e)}")
        return {"status": "error", "message": str(e)}


def extract_yaml_content(text):
    """Extract YAML from agent output (handles fenced code blocks and raw YAML)."""
    if not text:
        return ""

    fenced_match = re.search(
        r"```(?:yaml)?\s*\n(.*?)\n```", text, re.DOTALL | re.IGNORECASE
    )
    if fenced_match:
        return fenced_match.group(1).strip()

    yaml_lines = []
    capturing = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(("name:", "on:", "jobs:", "workflow_dispatch:")):
            capturing = True
        if capturing:
            yaml_lines.append(line)

    return "\n".join(yaml_lines).strip()


def _normalize_github_lambda_response(response):
    """Normalize responses from the GitHub API Lambda regardless of invocation format."""
    if isinstance(response, dict):
        if response.get("messageVersion") == "1.0":
            try:
                body = (
                    response.get("response", {})
                    .get("responseBody", {})
                    .get("application/json", {})
                    .get("body")
                )
                if isinstance(body, str):
                    return json.loads(body)
                return body or {"status": "error", "message": "Empty response body"}
            except Exception as exc:  # pragma: no cover - defensive
                return {
                    "status": "error",
                    "message": f"Invalid Bedrock wrapper response: {exc}",
                }
        return response
    return {"status": "error", "message": "Unexpected response format"}


def execute_github_workflow(
    owner,
    repo_name,
    branch_name,
    yaml_content,
    pr_title,
    pr_body,
    base_branch="main",
):
    """
    Orchestrate GitHub operations via the GitHub API Lambda.
    Returns a dict with success flag plus individual operation responses.
    """
    if not GITHUB_API_FUNCTION_NAME:
        return {
            "success": False,
            "error": "GITHUB_API_FUNCTION_NAME is not set in the environment",
        }

    operations = {}
    try:
        branch_payload = {
            "operation": "create_branch",
            "owner": owner,
            "repo": repo_name,
            "branch": branch_name,
            "base_branch": base_branch,
        }
        branch_resp = _normalize_github_lambda_response(
            invoke_lambda(GITHUB_API_FUNCTION_NAME, branch_payload)
        )
        operations["create_branch"] = branch_resp
        if branch_resp.get("status") != "success":
            return {
                "success": False,
                "error": branch_resp.get("message", "Branch creation failed"),
                "operations": operations,
            }

        # Generate unique commit message with timestamp
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")
        commit_message = f"Add CI/CD pipeline workflow - Generated at {timestamp}"
        
        file_payload = {
            "operation": "create_file",
            "owner": owner,
            "repo": repo_name,
            "branch": branch_name,
            "files": [
                {
                    "path": ".github/workflows/ci-cd.yml",
                    "content": yaml_content,
                    "message": commit_message,
                }
            ],
        }
        file_resp = _normalize_github_lambda_response(
            invoke_lambda(GITHUB_API_FUNCTION_NAME, file_payload)
        )
        operations["create_file"] = file_resp
        if file_resp.get("status") != "success":
            return {
                "success": False,
                "error": file_resp.get("message", "Workflow file creation failed"),
                "operations": operations,
            }

        pr_payload = {
            "operation": "create_pr",
            "owner": owner,
            "repo": repo_name,
            "title": pr_title,
            "head": branch_name,
            "base": base_branch,
            "draft": True,
            "body": pr_body,
        }
        pr_resp = _normalize_github_lambda_response(
            invoke_lambda(GITHUB_API_FUNCTION_NAME, pr_payload)
        )
        operations["create_pr"] = pr_resp
        if pr_resp.get("status") != "success":
            message = (pr_resp.get("message") or "").lower()
            if "already exists" in message:
                pr_resp["status"] = "warning"
                return {
                    "success": True,
                    "operations": operations,
                    "warnings": [
                        "Pull request already exists for branch; reused existing PR"
                    ],
                }
            return {
                "success": False,
                "error": pr_resp.get("message", "PR creation failed"),
                "operations": operations,
            }

        return {"success": True, "operations": operations}
    except Exception as exc:  # pragma: no cover - defensive
        return {
            "success": False,
            "error": str(exc),
            "operations": operations or None,
        }


def lambda_handler(event, context):
    """
    Event: {
        "task_id": "unique-task-id",
        "repo_url": "https://github.com/owner/repo",
        "branch": "main",
        "agent_ids": {
            "repo_scanner": "...",
            "pipeline_designer": "...",
            "security_compliance": "...",
            "yaml_generator": "...",
            "pr_manager": "..."
        }
    }
    """
    task_id = event.get("task_id") or context.aws_request_id
    repo_url = event.get("repo_url")
    branch = event.get("branch", "main")
    agent_ids = event.get("agent_ids", {})

    if not repo_url:
        return {"status": "error", "message": "repo_url required"}

    # Create task record
    create_task_record(task_id, repo_url)

    workflow_steps = []
    repo_scanner_summary = ""
    repo_ingestion_result = None
    pipeline_design_result = None
    security_recommendations = ""
    yaml_content = ""

    repo_match = re.search(r"github\.com/([^/]+)/([^/]+)", repo_url or "")
    repo_owner = repo_match.group(1) if repo_match else "unknown"
    repo_name = repo_match.group(2).rstrip("/") if repo_match else "unknown"

    if REPO_INGESTOR_FUNCTION_NAME:
        try:
            print(f"Invoking repo ingestor for {repo_url} ({branch})")
            repo_ingestion_payload = {"repo_url": repo_url, "branch": branch}
            repo_ingestion_result = invoke_lambda(
                REPO_INGESTOR_FUNCTION_NAME, repo_ingestion_payload
            )
            workflow_steps.append(
                {"step": "repo_ingestor", "result": repo_ingestion_result}
            )
            # Update DynamoDB with current progress
            update_task_status(task_id, "in_progress", {"steps": workflow_steps})
            if repo_ingestion_result.get("status") != "success":
                print(
                    f"Warning: Repo ingestor returned status {repo_ingestion_result.get('status')}: {repo_ingestion_result.get('message', 'no message')}"
                )
        except Exception as e:
            print(f"Warning: Repo ingestor invocation failed: {e}")
    else:
        print(
            "Warning: REPO_INGESTOR_FUNCTION_NAME not set, skipping manifest extraction"
        )

    try:
        # Step 1: Repository Scanner Agent
        if "repo_scanner" in agent_ids:
            session_id = f"{task_id}-repo-scanner"
            manifest_context = ""
            if (
                repo_ingestion_result
                and repo_ingestion_result.get("status") == "success"
            ):
                manifest_context = json.dumps(
                    repo_ingestion_result.get("manifests", {}),
                    indent=2,
                )
            else:
                manifest_context = "No manifest data is available (ingestion failed)."

            input_text = format_prompt(
                "repo_scanner",
                repo_url=repo_url,
                branch=branch,
                manifest_context=manifest_context,
            )

            result = invoke_agent(
                agent_ids["repo_scanner"], AGENT_ALIAS_ID, session_id, input_text
            )
            workflow_steps.append({"step": "repo_scanner", "result": result})
            # Update DynamoDB with current progress
            update_task_status(task_id, "in_progress", {"steps": workflow_steps})

            if result.get("status") != "success":
                update_task_status(
                    task_id,
                    "failed",
                    {"error": "Repo scanner failed", "step": "repo_scanner"},
                )
                return {
                    "status": "error",
                    "message": "Repository scanning failed",
                    "steps": workflow_steps,
                }
            repo_scanner_summary = result.get("completion", "")

        # Step 2: Static Analyzer (Lambda call, not agent)
        static_analyzer_result = None
        if STATIC_ANALYZER_FUNCTION_NAME:
            print(f"Invoking static analyzer: {STATIC_ANALYZER_FUNCTION_NAME}")
            static_analyzer_payload = {
                "repo_url": repo_url,
                "branch": branch,
                "analysis_types": ["dockerfile", "dependencies", "tests", "terraform"],
            }
            static_analyzer_result = invoke_lambda(
                STATIC_ANALYZER_FUNCTION_NAME, static_analyzer_payload
            )
            workflow_steps.append(
                {"step": "static_analyzer", "result": static_analyzer_result}
            )
            # Update DynamoDB with current progress
            update_task_status(task_id, "in_progress", {"steps": workflow_steps})

            if static_analyzer_result.get("status") != "success":
                error_msg = static_analyzer_result.get("message", "Unknown error")
                print(
                    f"Warning: Static analyzer returned status '{static_analyzer_result.get('status')}': {error_msg}"
                )
                print(
                    f"Static analyzer result: {json.dumps(static_analyzer_result, indent=2)}"
                )
            else:
                print("Static analyzer completed successfully")
                print(
                    f"Found {len(static_analyzer_result.get('dockerfile_analysis', []))} Dockerfiles"
                )
                print(
                    f"Found {len(static_analyzer_result.get('dependency_analysis', []))} dependency manifests"
                )
        else:
            print(
                "Warning: STATIC_ANALYZER_FUNCTION_NAME not set, skipping static analysis"
            )

        # Step 3: Pipeline Designer Agent
        if "pipeline_designer" in agent_ids:
            session_id = f"{task_id}-pipeline-designer"
            repo_analysis = repo_scanner_summary
            input_text = format_prompt(
                "pipeline_designer",
                repo_analysis=repo_analysis,
            )

            result = invoke_agent(
                agent_ids["pipeline_designer"], AGENT_ALIAS_ID, session_id, input_text
            )
            workflow_steps.append({"step": "pipeline_designer", "result": result})
            pipeline_design_result = result
            # Update DynamoDB with current progress
            update_task_status(task_id, "in_progress", {"steps": workflow_steps})

        # Step 4: Security & Compliance Agent
        if "security_compliance" in agent_ids:
            session_id = f"{task_id}-security-compliance"
            pipeline_design = (
                (pipeline_design_result or {}).get("completion", "")
                if isinstance(pipeline_design_result, dict)
                else ""
            )
            
            # Include static analyzer results if available (even if status is not success, include what we have)
            analysis_context = ""
            if static_analyzer_result:
                if static_analyzer_result.get("status") == "success":
                    analysis_context = f"\n\nStatic Analysis Results:\n{json.dumps(static_analyzer_result, indent=2)}"
                else:
                    # Include error information so agent knows static analysis failed
                    analysis_context = f"\n\nNote: Static analysis encountered an issue: {static_analyzer_result.get('message', 'Unknown error')}. Please proceed with security review based on the pipeline design."
            
            input_text = format_prompt(
                "security_compliance",
                pipeline_design=pipeline_design,
                analysis_context=analysis_context,
            )

            result = invoke_agent(
                agent_ids["security_compliance"],
                AGENT_ALIAS_ID,
                session_id,
                input_text,
            )
            workflow_steps.append({"step": "security_compliance", "result": result})
            security_recommendations = result.get("completion", "")
            # Update DynamoDB with current progress
            update_task_status(task_id, "in_progress", {"steps": workflow_steps})

            if result.get("status") != "success":
                print(
                    f"Warning: Security & Compliance agent returned: {result.get('status')}"
                )
                print(f"Error message: {result.get('message', 'No error message')}")

        # Step 5: YAML Generator Agent
        if "yaml_generator" in agent_ids:
            pipeline_design = (
                (pipeline_design_result or {}).get("completion", "")
                if isinstance(pipeline_design_result, dict)
                else ""
            )
            
            # Build ECR and ECS guidance based on Terraform analysis
            ecr_guidance = ""
            ecs_guidance = ""
            terraform_analysis = None
            if static_analyzer_result and static_analyzer_result.get("status") == "success":
                terraform_analysis = static_analyzer_result.get("terraform_analysis", {})
            
            # Build ECR guidance
            if terraform_analysis and terraform_analysis.get("has_ecr"):
                ecr_resources = terraform_analysis.get("ecr_resources", [])
                ecr_outputs = terraform_analysis.get("ecr_outputs", [])
                
                ecr_guidance = """CRITICAL: ECR resources are defined in Terraform. Infrastructure MUST be deployed BEFORE container build.

JOB SEQUENCING REQUIREMENTS:
- Create an "infrastructure" job that runs BEFORE the "container" job
- The infrastructure job must:
  1. Setup Terraform CLI (hashicorp/setup-terraform@v3 with cli_config_credentials_token) BEFORE any terraform commands
  2. Configure AWS credentials via OIDC
  3. Run terraform init, plan, and apply to create ECR resources
  4. Output ECR_REGISTRY and ECR_REPOSITORY as job outputs or environment variables
- The container job must:
  1. Depend on infrastructure job completion (use needs: [infrastructure])
  2. Get ECR values from infrastructure job outputs or run terraform output
  3. Use these values in Docker build/push steps

TERRAFORM SETUP ORDER (MUST BE FIRST):
- Setup Terraform CLI with cli_config_credentials_token BEFORE terraform init
- Example:
  - name: Setup Terraform
    uses: hashicorp/setup-terraform@v3
    with:
      cli_config_credentials_token: ${{{{ secrets.TF_API_TOKEN }}}}
  - name: Terraform Init
    run: terraform init

ECR VALUE EXTRACTION:
- If Terraform outputs exist for ECR, use them:
  - Add step: `terraform output -json` to get outputs
  - Extract: `ECR_REGISTRY=$(jq -r '.ecr_registry.value' terraform_outputs.json)`
  - Extract: `ECR_REPOSITORY=$(jq -r '.ecr_repository.value' terraform_outputs.json)`
- If outputs don't exist, derive from resources:
  - Get AWS account ID: `aws sts get-caller-identity --query Account --output text`
  - Construct registry: `${ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com`
  - Extract repository name from aws_ecr_repository resource

WORKFLOW STRUCTURE:
jobs:
  infrastructure:
    runs-on: ubuntu-latest
    needs: [quality, security]  # or appropriate dependencies
    permissions:
      id-token: write  # REQUIRED for OIDC authentication
      contents: read   # Required for checkout
    steps:
      - Setup Terraform CLI (with cli_config_credentials_token)
      - Configure AWS credentials
      - terraform init
      - terraform plan
      - terraform apply
      - Get ECR outputs and set as job outputs
  
  container:
    runs-on: ubuntu-latest
    needs: [infrastructure]  # CRITICAL: Must wait for infrastructure
    permissions:
      id-token: write  # REQUIRED for OIDC authentication
      contents: read   # Required for checkout
    steps:
      - Get ECR values from infrastructure job or terraform output
      - Build and push Docker image

- DO NOT use vars.ECR_REGISTRY or vars.ECR_REPOSITORY if ECR is managed by Terraform.
- CRITICAL: Every job that uses aws-actions/configure-aws-credentials@v4 MUST have `permissions: id-token: write` or OIDC will fail."""
            else:
                ecr_guidance = """- If ECR_REGISTRY and ECR_REPOSITORY are pre-configured as GitHub variables, use:
  - ECR_REGISTRY: ${{{{ vars.ECR_REGISTRY }}}}
  - ECR_REPOSITORY: ${{{{ vars.ECR_REPOSITORY }}}}

- If ECR resources are created by Terraform:
  - Infrastructure job MUST run before container build job
  - Setup Terraform CLI (with cli_config_credentials_token) BEFORE any terraform commands
  - Deploy infrastructure first, then extract ECR values from outputs
  - Container job must depend on infrastructure job (needs: [infrastructure])"""
            
            # Build ECS guidance
            if terraform_analysis and terraform_analysis.get("has_ecs"):
                ecs_resources = terraform_analysis.get("ecs_resources", [])
                ecs_outputs = terraform_analysis.get("ecs_outputs", [])
                
                ecs_guidance = """CRITICAL: ECS resources are defined in Terraform. Infrastructure MUST be deployed BEFORE deploy job.

JOB SEQUENCING REQUIREMENTS:
- Create an "infrastructure" job that runs BEFORE the "deploy" job
- The infrastructure job must:
  1. Setup Terraform CLI (hashicorp/setup-terraform@v3 with cli_config_credentials_token) BEFORE any terraform commands
  2. Configure AWS credentials via OIDC
  3. Run terraform init, plan, and apply to create ECS resources
  4. Output ECS_CLUSTER and ECS_SERVICE as job outputs
- The deploy job must:
  1. Depend on infrastructure job completion (use needs: [infrastructure])
  2. Get ECS values from infrastructure job outputs or run terraform output
  3. Use these values in ECS deployment commands

ECS VALUE EXTRACTION:
- If Terraform outputs exist for ECS, use them:
  - Add step in infrastructure job to extract ECS outputs:
    - name: Get ECS Details
      id: ecs-details
      run: |
        echo "cluster=$(terraform output -raw ecs_cluster)" >> $GITHUB_OUTPUT
        echo "service=$(terraform output -raw ecs_service)" >> $GITHUB_OUTPUT
  - Add to infrastructure job outputs section:
    outputs:
      ecs_cluster: ${{ steps.ecs-details.outputs.cluster }}
      ecs_service: ${{ steps.ecs-details.outputs.service }}
- In deploy job, use infrastructure job outputs:
  - name: Update ECS Service
    env:
      ECS_CLUSTER: ${{ needs.infrastructure.outputs.ecs_cluster }}
      ECS_SERVICE: ${{ needs.infrastructure.outputs.ecs_service }}
    run: aws ecs update-service --cluster ${{ env.ECS_CLUSTER }} --service ${{ env.ECS_SERVICE }} --force-new-deployment

- DO NOT use secrets.ECS_CLUSTER or secrets.ECS_SERVICE if ECS is managed by Terraform.
- CRITICAL: Every job that uses aws-actions/configure-aws-credentials@v4 MUST have `permissions: id-token: write` or OIDC will fail."""
            else:
                ecs_guidance = """- If ECS_CLUSTER and ECS_SERVICE are pre-configured as GitHub secrets, use:
  - ECS_CLUSTER: ${{{{ secrets.ECS_CLUSTER }}}}
  - ECS_SERVICE: ${{{{ secrets.ECS_SERVICE }}}}

- If ECS resources are created by Terraform:
  - Infrastructure job MUST run before deploy job
  - Setup Terraform CLI (with cli_config_credentials_token) BEFORE any terraform commands
  - Deploy infrastructure first, then extract ECS values from outputs
  - Deploy job must depend on infrastructure job (needs: [infrastructure])"""
            
            base_prompt = format_prompt(
                "yaml_generator_base",
                pipeline_design=pipeline_design,
                ecr_guidance=ecr_guidance,
                ecs_guidance=ecs_guidance,
            )

            max_yaml_attempts = 2
            yaml_content = ""

            for attempt in range(1, max_yaml_attempts + 1):
                session_id = f"{task_id}-yaml-generator-attempt-{attempt}"
                prompt = (
                    base_prompt
                    if attempt == 1
                    else format_prompt(
                        "yaml_generator_retry",
                        base_prompt=base_prompt,
                    )
                )

                result = invoke_agent(
                    agent_ids["yaml_generator"], AGENT_ALIAS_ID, session_id, prompt
                )
                workflow_steps.append(
                    {"step": f"yaml_generator_attempt_{attempt}", "result": result}
                )
                # Update DynamoDB with current progress
                update_task_status(task_id, "in_progress", {"steps": workflow_steps})

                if result.get("status") != "success":
                    if attempt == max_yaml_attempts:
                        update_task_status(
                            task_id,
                            "failed",
                            {
                                "error": "YAML generation failed",
                                "step": "yaml_generator",
                                "steps": workflow_steps,
                            },
                        )
                        return {
                            "status": "error",
                            "message": "YAML generation failed",
                            "steps": workflow_steps,
                        }
                    print(
                        f"YAML generator attempt {attempt} failed with status {result.get('status')} – retrying."
                    )
                    continue

                raw_yaml_output = result.get("completion", "")
                yaml_content = extract_yaml_content(raw_yaml_output)
                print(f"Extracted YAML content length: {len(yaml_content)}")
                if yaml_content:
                    print(f"YAML preview: {yaml_content[:200]}")

                if yaml_content and len(yaml_content.strip()) >= 50:
                    break

                print(
                    f"YAML generator attempt {attempt} did not include a usable workflow (length={len(yaml_content)})."
                )
                yaml_content = ""

            if not yaml_content:
                update_task_status(
                    task_id,
                    "failed",
                    {
                        "error": "YAML content is empty or too short",
                        "step": "yaml_generator",
                        "steps": workflow_steps,
                    },
                )
                return {
                    "status": "error",
                    "message": "YAML content is empty or too short",
                    "steps": workflow_steps,
                }

            if TEMPLATE_VALIDATOR_FUNCTION_NAME:
                validator_payload = {
                    "yaml_content": yaml_content,
                    "validation_level": "normal",
                }
                validator_result = invoke_lambda(
                    TEMPLATE_VALIDATOR_FUNCTION_NAME, validator_payload
                )
                if "status" not in validator_result:
                    validator_result["status"] = (
                        "success"
                        if validator_result.get("valid")
                        else "validation_failed"
                    )
                workflow_steps.append(
                    {"step": "template_validator", "result": validator_result}
                )
                # Update DynamoDB with current progress
                update_task_status(task_id, "in_progress", {"steps": workflow_steps})
                if not validator_result.get("valid", False):
                    summary_errors = (
                        validator_result.get("summary", {}).get("errors")
                        or validator_result.get("syntax", {}).get("errors")
                        or []
                    )
                    detail = "; ".join(summary_errors[:3])
                    error_msg = "Template validator reported invalid YAML" + (
                        f": {detail}" if detail else ""
                    )
                    print(f"Template validator errors: {summary_errors}")
                    print(f"Invalid YAML content:\n{yaml_content}")
                    update_task_status(
                        task_id,
                        "failed",
                        {
                            "error": error_msg,
                            "step": "template_validator",
                            "steps": workflow_steps,
                        },
                    )
                    return {
                        "status": "error",
                        "message": error_msg,
                        "steps": workflow_steps,
                    }
            else:
                print(
                    "Warning: TEMPLATE_VALIDATOR_FUNCTION_NAME not set, skipping YAML validation"
                )

        # Step 6: PR Manager Agent (documentation only)
        pr_body = ""
        # Generate unique PR title with timestamp
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")
        pr_title = f"Add CI/CD pipeline for {repo_name} - Generated at {timestamp}"
        if "pr_manager" in agent_ids:
            session_id = f"{task_id}-pr-manager"
            pipeline_summary = (
                (pipeline_design_result or {}).get("completion", "")
                if isinstance(pipeline_design_result, dict)
                else ""
            )
            security_summary = (
                security_recommendations or "Security review not available."
            )
            yaml_section = (
                f"```yaml\n{yaml_content}\n```"
                if yaml_content
                else "YAML generation failed."
            )

            input_text = format_prompt(
                "pr_manager",
                repo_url=repo_url,
                branch=branch,
                pipeline_summary=pipeline_summary,
                security_summary=security_summary,
                yaml_section=yaml_section,
            )

            result = invoke_agent(
                agent_ids["pr_manager"], AGENT_ALIAS_ID, session_id, input_text
            )
            workflow_steps.append({"step": "pr_manager", "result": result})
            pr_body = result.get("completion", "").strip()
            # Add timestamp to agent-generated PR body for uniqueness
            if pr_body:
                pr_body_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")
                pr_body = f"{pr_body}\n\n---\n**Generated at:** {pr_body_timestamp}"
            # Update DynamoDB with current progress
            update_task_status(task_id, "in_progress", {"steps": workflow_steps})

            if not pr_body:
                print(
                    "PR Manager agent returned empty content; using default PR template."
                )

        if not pr_body:
            # Generate unique PR body with timestamp
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")
            pr_body = format_prompt(
                "pr_body_default",
                timestamp=timestamp,
            )

        if yaml_content:
            # Use consistent branch name for CI/CD generation
            github_branch = "gen-ai/cicd-generation"
            github_result = execute_github_workflow(
                repo_owner,
                repo_name,
                github_branch,
                yaml_content,
                pr_title,
                pr_body,
                base_branch=branch,
            )
            github_result["status"] = (
                "success" if github_result.get("success") else "error"
            )
            workflow_steps.append(
                {"step": "github_operations", "result": github_result}
            )
            # Update DynamoDB with current progress (final step)
            update_task_status(task_id, "in_progress", {"steps": workflow_steps})

            if not github_result.get("success"):
                update_task_status(
                    task_id,
                    "failed",
                    {
                        "error": github_result.get("error", "GitHub operations failed"),
                        "step": "github_operations",
                        "steps": workflow_steps,
                    },
                )
                return {
                    "status": "error",
                    "message": github_result.get("error", "GitHub operations failed"),
                    "steps": workflow_steps,
                }
        else:
            error_msg = "YAML content missing; cannot update GitHub"
            update_task_status(
                task_id,
                "failed",
                {"error": error_msg, "step": "yaml_generator"},
            )
            return {
                "status": "error",
                "message": error_msg,
                "steps": workflow_steps,
            }

        # Update task as completed
        update_task_status(task_id, "completed", {"steps": workflow_steps})

        return {
            "status": "success",
            "task_id": task_id,
            "workflow_steps": workflow_steps,
        }

    except Exception as e:
        update_task_status(task_id, "failed", {"error": str(e)})
        return {
            "status": "error",
            "message": str(e),
            "task_id": task_id,
            "workflow_steps": workflow_steps,
        }
