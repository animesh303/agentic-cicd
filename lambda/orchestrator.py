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
s3_client = boto3.client("s3", region_name=AWS_REGION)

# Initialize DynamoDB table for task tracking (create separately in Terraform)
TASK_TABLE_NAME = os.environ.get("TASK_TABLE_NAME", "agentic-cicd-tasks")
AGENT_ALIAS_ID = os.environ.get("AGENT_ALIAS_ID", "TSTALIASID")
REPO_INGESTOR_FUNCTION_NAME = os.environ.get("REPO_INGESTOR_FUNCTION_NAME")
STATIC_ANALYZER_FUNCTION_NAME = os.environ.get("STATIC_ANALYZER_FUNCTION_NAME")
TEMPLATE_VALIDATOR_FUNCTION_NAME = os.environ.get("TEMPLATE_VALIDATOR_FUNCTION_NAME")
GITHUB_API_FUNCTION_NAME = os.environ.get("GITHUB_API_FUNCTION_NAME")
S3_ARTIFACT_BUCKET = os.environ.get("S3_ARTIFACT_BUCKET", "agentic-cicd-artifacts")


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


def upload_artifact_to_s3(task_id, step_name, artifact_data, artifact_type="json"):
    """Upload artifact to S3 for troubleshooting and debugging"""
    if not S3_ARTIFACT_BUCKET:
        print(f"Warning: S3_ARTIFACT_BUCKET not configured, skipping artifact upload for {step_name}")
        return None
    
    try:
        timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%S")
        # S3 path: artifacts/{task_id}/{step_name}/{timestamp}.{extension}
        s3_key = f"artifacts/{task_id}/{step_name}/{timestamp}.{artifact_type}"
        
        # Convert data to string if it's not already
        if isinstance(artifact_data, (dict, list)):
            content = json.dumps(artifact_data, indent=2, default=str)
            content_type = "application/json"
        else:
            content = str(artifact_data)
            content_type = "text/plain"
        
        s3_client.put_object(
            Bucket=S3_ARTIFACT_BUCKET,
            Key=s3_key,
            Body=content.encode('utf-8'),
            ContentType=content_type,
            Metadata={
                "task_id": task_id,
                "step_name": step_name,
                "timestamp": timestamp
            }
        )
        
        s3_url = f"s3://{S3_ARTIFACT_BUCKET}/{s3_key}"
        print(f"Uploaded artifact for {step_name} to {s3_url}")
        return s3_url
    except Exception as e:
        print(f"Warning: Could not upload artifact to S3 for {step_name}: {e}")
        return None


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
            # Log last 200 chars to detect truncation
            if len(completion) > 200:
                print(f"Response ends with: ...{completion[-200:]}")
            else:
                print(f"Full response: {completion}")
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

    # Try to find fenced code block - use greedy match to get everything until the last ```
    fenced_match = re.search(
        r"```(?:yaml)?\s*\n(.*?)(?:\n```|$)", text, re.DOTALL | re.IGNORECASE
    )
    if fenced_match:
        yaml_content = fenced_match.group(1).strip()
        # If the content doesn't end with ```, it might be incomplete
        # Check if there's a closing ``` after our match
        remaining_text = text[fenced_match.end():]
        if "```" not in remaining_text[:100]:  # Check if closing ``` is nearby
            # Might be incomplete, but return what we have
            print(f"Warning: YAML code block might be incomplete (no closing ``` found nearby)")
        return yaml_content

    # Fallback: extract YAML lines
    yaml_lines = []
    capturing = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(("name:", "on:", "jobs:", "workflow_dispatch:")):
            capturing = True
        if capturing:
            yaml_lines.append(line)

    return "\n".join(yaml_lines).strip()


def extract_multiple_yaml_workflows(text):
    """
    Extract multiple YAML workflows from agent output.
    Returns a dict with 'ci' and 'cd' keys, each containing YAML content.
    """
    if not text:
        return {"ci": "", "cd": ""}
    
    workflows = {"ci": "", "cd": ""}
    
    # Find all YAML code blocks
    yaml_blocks = re.findall(
        r"```(?:yaml)?\s*\n(.*?)\n```", text, re.DOTALL | re.IGNORECASE
    )
    
    if not yaml_blocks:
        # Fallback: try to find single block or extract from text
        single_yaml = extract_yaml_content(text)
        if single_yaml:
            # Try to determine if it's CI or CD based on triggers
            if "types:\n        - opened" in single_yaml or 'types: [opened]' in single_yaml:
                workflows["ci"] = single_yaml
            elif "types:\n        - closed" in single_yaml or 'types: [closed]' in single_yaml:
                workflows["cd"] = single_yaml
            else:
                # Default: assume it's a combined workflow, split it
                # For now, assign to CD as fallback
                workflows["cd"] = single_yaml
        return workflows
    
    # Process each YAML block
    for yaml_content in yaml_blocks:
        yaml_content = yaml_content.strip()
        if not yaml_content:
            continue
        
        # Determine if this is CI or CD workflow based on triggers and content
        is_ci = False
        is_cd = False
        
        # Check trigger types
        if "types:\n        - opened" in yaml_content or 'types: [opened]' in yaml_content or 'types:\n      - opened' in yaml_content:
            is_ci = True
        elif "types:\n        - closed" in yaml_content or 'types: [closed]' in yaml_content or 'types:\n      - closed' in yaml_content:
            is_cd = True
        
        # Check workflow name
        if "name: CI" in yaml_content or "name: ci" in yaml_content or "CI Pipeline" in yaml_content:
            is_ci = True
        elif "name: CD" in yaml_content or "name: cd" in yaml_content or "CD Pipeline" in yaml_content:
            is_cd = True
        
        # Check content - CI has security scans, CD has deployment
        if not is_ci and not is_cd:
            if any(job in yaml_content.lower() for job in ["sast", "sca", "secrets-scan", "iac-scan"]):
                is_ci = True
            elif any(job in yaml_content.lower() for job in ["deploy", "infrastructure", "build"]):
                is_cd = True
        
        # Assign to appropriate workflow
        if is_ci:
            workflows["ci"] = yaml_content
            print("Identified CI workflow")
        elif is_cd:
            workflows["cd"] = yaml_content
            print("Identified CD workflow")
        else:
            # If we can't determine, check if we already have one assigned
            # If neither is set, assign based on order (first = CI, second = CD)
            if not workflows["ci"]:
                workflows["ci"] = yaml_content
                print("Assigned first workflow as CI (default)")
            elif not workflows["cd"]:
                workflows["cd"] = yaml_content
                print("Assigned second workflow as CD (default)")
    
    return workflows


def is_yaml_complete(yaml_content):
    """Check if YAML content appears complete (not truncated mid-line or mid-block)."""
    if not yaml_content:
        return False
    
    # Check for common signs of incomplete YAML:
    # 1. Last line doesn't end with newline and is incomplete (ends with $ or incomplete quote)
    lines = yaml_content.splitlines()
    if lines:
        last_line = lines[-1].strip()
        # Check if last line looks incomplete
        if last_line and not last_line.endswith((':', '-', ']', '}', '>', '|')):
            # Check if it ends with incomplete string or variable reference
            if last_line.endswith('${{') or last_line.endswith('${{ needs') or last_line.endswith('${{ vars') or last_line.endswith('${{ secrets'):
                print(f"Warning: YAML appears incomplete - last line ends with incomplete variable reference: {last_line[-50:]}")
                return False
            # Check if it ends mid-string (unclosed quote)
            if last_line.count('"') % 2 != 0 or last_line.count("'") % 2 != 0:
                print(f"Warning: YAML appears incomplete - last line has unclosed quotes: {last_line[-50:]}")
                return False
    
    # Check for balanced braces/brackets in last few lines
    last_50_chars = yaml_content[-50:]
    open_braces = last_50_chars.count('{')
    close_braces = last_50_chars.count('}')
    if open_braces > close_braces:
        print(f"Warning: YAML appears incomplete - unclosed braces in last 50 chars")
        return False
    
    # Enhanced checks for workflow completeness
    # Check if deploy job exists and is complete
    if "deploy:" in yaml_content.lower():
        deploy_section = yaml_content[yaml_content.lower().rfind("deploy:"):]
        # Check if deploy job has actual deployment steps (not just validation)
        # Should have ECS update command or similar deployment action
        has_deployment_action = any(keyword in deploy_section.lower() for keyword in [
            "aws ecs update-service",
            "aws ecs deploy",
            "ecs update-service",
            "update-service",
            "force-new-deployment",
            "deploy",
            "update service"
        ])
        if not has_deployment_action:
            # Check last 200 chars of deploy section to see if it ends mid-step
            last_200 = deploy_section[-200:].lower()
            # If it ends with validation/error checking but no actual deployment, it's incomplete
            if "exit 1" in last_200 or "error:" in last_200:
                # Check if there's more content after the error check
                # If the last meaningful line is just error checking, it's likely incomplete
                last_lines = [l.strip() for l in deploy_section.splitlines() if l.strip() and not l.strip().startswith('#')]
                if last_lines:
                    last_meaningful = last_lines[-1].lower()
                    # If last line is just error handling without deployment action, likely incomplete
                    if any(phrase in last_meaningful for phrase in ["exit 1", "echo \"error", "if [[ -z"]):
                        # Check if there's an ECS update command anywhere in deploy section
                        if "ecs" not in deploy_section.lower() or "update" not in deploy_section.lower():
                            print(f"Warning: YAML deploy job appears incomplete - ends with validation but no deployment action found")
                            print(f"Last 100 chars of deploy section: {deploy_section[-100:]}")
                            return False
    
    # Check if last step in any job appears incomplete (ends mid-command)
    # Look for run: blocks that don't seem to close properly
    last_300_chars = yaml_content[-300:]
    # If we're in a run: | block, check if it's properly closed
    if "run: |" in last_300_chars or "run:" in last_300_chars:
        # Count indentation of last non-empty line
        non_empty_lines = [l for l in lines if l.strip()]
        if non_empty_lines:
            last_non_empty = non_empty_lines[-1]
            # If last line has significant indentation (more than 8 spaces), might be mid-block
            if len(last_non_empty) - len(last_non_empty.lstrip()) > 8:
                # Check if it looks like it should continue (ends with backslash, pipe, or incomplete command)
                stripped = last_non_empty.strip()
                if stripped.endswith('\\') or stripped.endswith('|') or (stripped and not any(stripped.endswith(term) for term in [':', '-', ']', '}', 'fi', 'done', 'esac'])):
                    # But allow if it's a complete command ending
                    if not any(stripped.endswith(term) for term in ['|| true', '|| false', ';', '&']):
                        # Check if next expected line would be at same or less indentation
                        # This is a heuristic - if we're deep in a block and line doesn't end properly, might be truncated
                        print(f"Warning: YAML might be incomplete - last line appears to be mid-block: {stripped[-50:]}")
                        # Don't fail on this alone, but log it
    
    # Final check: ensure workflow has reasonable length (truncated workflows are usually short)
    # A complete workflow with multiple jobs should be at least 150 lines
    if len(lines) < 150 and ("deploy:" in yaml_content.lower() or "build:" in yaml_content.lower()):
        # Check if deploy job is present but seems short
        if "deploy:" in yaml_content.lower():
            deploy_start = yaml_content.lower().rfind("deploy:")
            deploy_content = yaml_content[deploy_start:]
            deploy_lines = [l for l in deploy_content.splitlines() if l.strip() and not l.strip().startswith('#')]
            # Deploy job should have at least 10-15 meaningful lines (steps, commands, etc.)
            if len(deploy_lines) < 10:
                print(f"Warning: YAML deploy job appears too short ({len(deploy_lines)} lines) - might be incomplete")
                return False
    
    return True


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
    yaml_content_ci,
    yaml_content_cd,
    pr_title,
    pr_body,
    base_branch="main",
):
    """
    Orchestrate GitHub operations via the GitHub API Lambda.
    Creates two separate workflow files: ci.yml and cd.yml
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
        commit_message = f"Add CI/CD pipeline workflows - Generated at {timestamp}"
        
        # Prepare files array with both CI and CD workflows
        files = []
        
        if yaml_content_ci:
            files.append({
                "path": ".github/workflows/ci.yml",
                "content": yaml_content_ci,
                "message": commit_message,
            })
        
        if yaml_content_cd:
            files.append({
                "path": ".github/workflows/cd.yml",
                "content": yaml_content_cd,
                "message": commit_message,
            })
        
        if not files:
            return {
                "success": False,
                "error": "No workflow content provided (both CI and CD are empty)",
                "operations": operations,
            }
        
        file_payload = {
            "operation": "create_file",
            "owner": owner,
            "repo": repo_name,
            "branch": branch_name,
            "files": files,
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
            # Upload artifact to S3
            upload_artifact_to_s3(task_id, "repo_ingestor", repo_ingestion_result)
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
            # Upload artifact to S3
            upload_artifact_to_s3(task_id, "repo_scanner", result)
            # Update DynamoDB with current progress
            update_task_status(task_id, "in_progress", {"steps": workflow_steps})

            if result.get("status") != "success":
                # Upload error artifact
                upload_artifact_to_s3(task_id, "repo_scanner_error", result)
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
            # Upload artifact to S3
            upload_artifact_to_s3(task_id, "static_analyzer", static_analyzer_result)
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

        # Extract repository structure for context
        repo_structure_context = ""
        if (
            repo_ingestion_result
            and repo_ingestion_result.get("status") == "success"
            and "repository_structure" in repo_ingestion_result
        ):
            structure = repo_ingestion_result.get("repository_structure", {})
            structure_text = "Repository Structure:\n"
            if structure.get("tree"):
                structure_text += "\n".join(structure["tree"][:50])  # Limit to first 50 lines
                if len(structure["tree"]) > 50:
                    structure_text += f"\n... (showing first 50 of {len(structure['tree'])} lines)"
            if structure.get("terraform_working_dir"):
                structure_text += f"\n\nTerraform Working Directory: {structure['terraform_working_dir']}"
            if structure.get("terraform_directories"):
                structure_text += f"\nTerraform Directories: {', '.join(structure['terraform_directories'])}"
            repo_structure_context = structure_text
        else:
            repo_structure_context = "Repository structure information not available."

        # Step 3: Pipeline Designer Agent
        if "pipeline_designer" in agent_ids:
            session_id = f"{task_id}-pipeline-designer"
            repo_analysis = repo_scanner_summary
            input_text = format_prompt(
                "pipeline_designer",
                repo_analysis=repo_analysis,
                repo_structure=repo_structure_context,
            )

            result = invoke_agent(
                agent_ids["pipeline_designer"], AGENT_ALIAS_ID, session_id, input_text
            )
            workflow_steps.append({"step": "pipeline_designer", "result": result})
            pipeline_design_result = result
            # Upload artifact to S3
            upload_artifact_to_s3(task_id, "pipeline_designer", result)
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
            # Upload artifact to S3
            upload_artifact_to_s3(task_id, "security_compliance", result)
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
            
            # Extract Terraform working directory from repository structure
            terraform_working_dir = "."
            if (
                repo_ingestion_result
                and repo_ingestion_result.get("status") == "success"
                and "repository_structure" in repo_ingestion_result
            ):
                structure = repo_ingestion_result.get("repository_structure", {})
                terraform_working_dir = structure.get("terraform_working_dir", ".")
            
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
                
                # Extract actual output names discovered from codebase analysis
                ecr_output_names = [out.get("output_name", "") for out in ecr_outputs if out.get("output_name")]
                
                # Find specific output names
                ecr_repository_url_output = next(
                    (out.get("output_name") for out in ecr_outputs 
                     if "repository_url" in out.get("output_name", "").lower() or 
                        "repo_url" in out.get("output_name", "").lower()), 
                    None
                )
                ecr_registry_output = next(
                    (out.get("output_name") for out in ecr_outputs 
                     if "registry" in out.get("output_name", "").lower() and 
                        "url" not in out.get("output_name", "").lower()), 
                    None
                )
                ecr_repository_output = next(
                    (out.get("output_name") for out in ecr_outputs 
                     if "repository" in out.get("output_name", "").lower() and 
                        "url" not in out.get("output_name", "").lower()), 
                    None
                )
                
                ecr_guidance = format_prompt(
                    "ecr_guidance_terraform",
                    terraform_working_dir=terraform_working_dir,
                    available_ecr_outputs=", ".join(ecr_output_names) if ecr_output_names else "none found",
                    ecr_repository_url_output=ecr_repository_url_output or "",
                    ecr_registry_output=ecr_registry_output or "",
                    ecr_repository_output=ecr_repository_output or "",
                )
            else:
                ecr_guidance = format_prompt("ecr_guidance_variables")
            
            # Build ECS guidance
            if terraform_analysis and terraform_analysis.get("has_ecs"):
                ecs_resources = terraform_analysis.get("ecs_resources", [])
                ecs_outputs = terraform_analysis.get("ecs_outputs", [])
                
                # Extract actual output names discovered from codebase analysis
                ecs_output_names = [out.get("output_name", "") for out in ecs_outputs if out.get("output_name")]
                
                # Find specific output names
                ecs_cluster_output = next(
                    (out.get("output_name") for out in ecs_outputs 
                     if "cluster" in out.get("output_name", "").lower()), 
                    None
                )
                ecs_service_output = next(
                    (out.get("output_name") for out in ecs_outputs 
                     if "service" in out.get("output_name", "").lower()), 
                    None
                )
                
                ecs_guidance = format_prompt(
                    "ecs_guidance_terraform",
                    terraform_working_dir=terraform_working_dir,
                    available_ecs_outputs=", ".join(ecs_output_names) if ecs_output_names else "none found",
                    ecs_cluster_output=ecs_cluster_output or "",
                    ecs_service_output=ecs_service_output or "",
                )
            else:
                ecs_guidance = format_prompt("ecs_guidance_variables")
            
            # Generate CI workflow first (separate agent call)
            print("Generating CI workflow...")
            ci_prompt = format_prompt(
                "yaml_generator_ci",
                pipeline_design=pipeline_design,
                repo_structure=repo_structure_context,
            )
            
            max_ci_attempts = 3
            yaml_content_ci = ""
            ci_validation_errors = None
            
            for ci_attempt in range(1, max_ci_attempts + 1):
                session_id = f"{task_id}-yaml-generator-ci-attempt-{ci_attempt}"
                
                if ci_attempt > 1 and ci_validation_errors:
                    # Retry with validation errors
                    prompt = f"{ci_prompt}\n\nPrevious attempt failed:\n{ci_validation_errors}\n\nPlease fix the issues and generate a complete CI workflow."
                else:
                    prompt = ci_prompt
                
                result = invoke_agent(
                    agent_ids["yaml_generator"], AGENT_ALIAS_ID, session_id, prompt
                )
                workflow_steps.append(
                    {"step": f"yaml_generator_ci_attempt_{ci_attempt}", "result": result}
                )
                upload_artifact_to_s3(task_id, f"yaml_generator_ci_attempt_{ci_attempt}", result)
                update_task_status(task_id, "in_progress", {"steps": workflow_steps})
                
                if result.get("status") != "success":
                    if ci_attempt == max_ci_attempts:
                        update_task_status(task_id, "failed", {"error": "CI workflow generation failed", "step": "yaml_generator_ci"})
                        return {"status": "error", "message": "CI workflow generation failed", "steps": workflow_steps}
                    continue
                
                raw_output = result.get("completion", "")
                yaml_content_ci = extract_yaml_content(raw_output)
                
                if not yaml_content_ci or len(yaml_content_ci.strip()) < 50:
                    ci_validation_errors = "CI workflow is missing or too short. Generate a complete CI workflow with all security scanning jobs."
                    if ci_attempt == max_ci_attempts:
                        return {"status": "error", "message": "CI workflow content is empty or too short", "steps": workflow_steps}
                    continue
                
                if not is_yaml_complete(yaml_content_ci):
                    ci_validation_errors = "CI workflow appears incomplete or truncated. Ensure all security scanning jobs are complete."
                    if ci_attempt == max_ci_attempts:
                        return {"status": "error", "message": "CI workflow is incomplete", "steps": workflow_steps}
                    continue
                
                # Validate CI workflow
                if TEMPLATE_VALIDATOR_FUNCTION_NAME:
                    validator_result = invoke_lambda(
                        TEMPLATE_VALIDATOR_FUNCTION_NAME,
                        {"yaml_content": yaml_content_ci, "validation_level": "normal"}
                    )
                    if not validator_result.get("valid", False):
                        errors = validator_result.get("summary", {}).get("errors", []) or validator_result.get("syntax", {}).get("errors", [])
                        ci_validation_errors = "\n".join(errors) if errors else "CI workflow validation failed"
                        if ci_attempt == max_ci_attempts:
                            return {"status": "error", "message": "CI workflow validation failed", "steps": workflow_steps}
                        continue
                
                print(f"CI workflow generated successfully (length: {len(yaml_content_ci)})")
                break
            
            if not yaml_content_ci:
                return {"status": "error", "message": "Failed to generate CI workflow", "steps": workflow_steps}
            
            # Generate CD workflow (separate agent call)
            print("Generating CD workflow...")
            cd_prompt = format_prompt(
                "yaml_generator_cd",
                pipeline_design=pipeline_design,
                ecr_guidance=ecr_guidance,
                ecs_guidance=ecs_guidance,
                repo_structure=repo_structure_context,
                terraform_working_dir=terraform_working_dir,
            )
            
            max_cd_attempts = 3
            yaml_content_cd = ""
            cd_validation_errors = None
            
            for cd_attempt in range(1, max_cd_attempts + 1):
                session_id = f"{task_id}-yaml-generator-cd-attempt-{cd_attempt}"
                
                if cd_attempt > 1 and cd_validation_errors:
                    # Retry with validation errors
                    prompt = f"{cd_prompt}\n\nPrevious attempt failed:\n{cd_validation_errors}\n\nPlease fix the issues and generate a complete CD workflow."
                else:
                    prompt = cd_prompt
                
                result = invoke_agent(
                    agent_ids["yaml_generator"], AGENT_ALIAS_ID, session_id, prompt
                )
                workflow_steps.append(
                    {"step": f"yaml_generator_cd_attempt_{cd_attempt}", "result": result}
                )
                upload_artifact_to_s3(task_id, f"yaml_generator_cd_attempt_{cd_attempt}", result)
                update_task_status(task_id, "in_progress", {"steps": workflow_steps})
                
                if result.get("status") != "success":
                    if cd_attempt == max_cd_attempts:
                        update_task_status(task_id, "failed", {"error": "CD workflow generation failed", "step": "yaml_generator_cd"})
                        return {"status": "error", "message": "CD workflow generation failed", "steps": workflow_steps}
                    continue
                
                raw_output = result.get("completion", "")
                yaml_content_cd = extract_yaml_content(raw_output)
                
                if not yaml_content_cd or len(yaml_content_cd.strip()) < 50:
                    cd_validation_errors = "CD workflow is missing or too short. Generate a complete CD workflow with infrastructure, build, and deploy jobs."
                    if cd_attempt == max_cd_attempts:
                        return {"status": "error", "message": "CD workflow content is empty or too short", "steps": workflow_steps}
                    continue
                
                if not is_yaml_complete(yaml_content_cd):
                    missing_parts = []
                    if "deploy:" in yaml_content_cd.lower():
                        deploy_section = yaml_content_cd[yaml_content_cd.lower().rfind("deploy:"):]
                        if "aws ecs update-service" not in deploy_section.lower():
                            missing_parts.append("Deploy job missing ECS update-service command")
                    cd_validation_errors = "CD workflow appears incomplete. " + ("; ".join(missing_parts) if missing_parts else "Ensure all jobs are complete.")
                    if cd_attempt == max_cd_attempts:
                        return {"status": "error", "message": "CD workflow is incomplete", "steps": workflow_steps}
                    continue
                
                # Validate CD workflow
                if TEMPLATE_VALIDATOR_FUNCTION_NAME:
                    validator_result = invoke_lambda(
                        TEMPLATE_VALIDATOR_FUNCTION_NAME,
                        {"yaml_content": yaml_content_cd, "validation_level": "normal"}
                    )
                    if not validator_result.get("valid", False):
                        errors = validator_result.get("summary", {}).get("errors", []) or validator_result.get("syntax", {}).get("errors", [])
                        cd_validation_errors = "\n".join(errors) if errors else "CD workflow validation failed"
                        if cd_attempt == max_cd_attempts:
                            return {"status": "error", "message": "CD workflow validation failed", "steps": workflow_steps}
                        continue
                
                print(f"CD workflow generated successfully (length: {len(yaml_content_cd)})")
                break
            
            if not yaml_content_cd:
                update_task_status(
                    task_id,
                    "failed",
                    {
                        "error": "Failed to generate CD workflow",
                        "step": "yaml_generator_cd",
                        "steps": workflow_steps,
                    },
                )
                return {
                    "status": "error",
                    "message": "Failed to generate CD workflow",
                    "steps": workflow_steps,
                }

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
            # Combine both workflows for PR description
            yaml_section = ""
            if yaml_content_ci:
                yaml_section += "## CI Workflow\n```yaml\n" + yaml_content_ci + "\n```\n\n"
            if yaml_content_cd:
                yaml_section += "## CD Workflow\n```yaml\n" + yaml_content_cd + "\n```\n"
            if not yaml_section:
                yaml_section = "YAML generation failed."

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
            # Upload artifact to S3
            upload_artifact_to_s3(task_id, "pr_manager", result)
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

        if yaml_content_ci and yaml_content_cd:
            # Use consistent branch name for CI/CD generation
            github_branch = "gen-ai/cicd-generation"
            github_result = execute_github_workflow(
                repo_owner,
                repo_name,
                github_branch,
                yaml_content_ci,
                yaml_content_cd,
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
            # Upload artifact to S3
            upload_artifact_to_s3(task_id, "github_operations", github_result)
            # Also upload the final YAML content that was committed
            if yaml_content_ci:
                upload_artifact_to_s3(task_id, "final_yaml_content_ci", yaml_content_ci, "yaml")
            if yaml_content_cd:
                upload_artifact_to_s3(task_id, "final_yaml_content_cd", yaml_content_cd, "yaml")
            # Update DynamoDB with current progress (final step)
            update_task_status(task_id, "in_progress", {"steps": workflow_steps})

            if not github_result.get("success"):
                # Upload error artifact (already uploaded above, but ensure it's there)
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
            error_msg = "One or both workflow contents missing; cannot update GitHub"
            # Upload error artifact
            error_artifact = {
                "error": error_msg,
                "has_ci": bool(yaml_content_ci),
                "has_cd": bool(yaml_content_cd),
                "workflow_steps": workflow_steps
            }
            upload_artifact_to_s3(task_id, "yaml_content_missing_error", error_artifact)
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
        
        # Upload final summary artifact with all workflow steps
        summary_artifact = {
            "task_id": task_id,
            "repo_url": repo_url,
            "branch": branch,
            "status": "completed",
            "workflow_steps": workflow_steps,
            "timestamp": datetime.utcnow().isoformat()
        }
        upload_artifact_to_s3(task_id, "workflow_summary", summary_artifact)

        return {
            "status": "success",
            "task_id": task_id,
            "workflow_steps": workflow_steps,
        }

    except Exception as e:
        update_task_status(task_id, "failed", {"error": str(e)})
        
        # Upload error summary artifact
        error_artifact = {
            "task_id": task_id,
            "repo_url": repo_url if 'repo_url' in locals() else "unknown",
            "status": "failed",
            "error": str(e),
            "workflow_steps": workflow_steps if 'workflow_steps' in locals() else [],
            "timestamp": datetime.utcnow().isoformat()
        }
        upload_artifact_to_s3(task_id, "workflow_error_summary", error_artifact)
        
        return {
            "status": "error",
            "message": str(e),
            "task_id": task_id,
            "workflow_steps": workflow_steps,
        }
