#!/usr/bin/env python3
"""
Orchestrator/Controller Lambda
Coordinates agents and tracks tasks. Manages the workflow between different agents.
"""
import json
import boto3
import os
from datetime import datetime
from botocore.config import Config

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
STATIC_ANALYZER_FUNCTION_NAME = os.environ.get("STATIC_ANALYZER_FUNCTION_NAME")


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
    owner, repo_name, branch_name, yaml_content, base_branch="main"
):
    """
    Directly orchestrate GitHub operations via the GitHub API Lambda.
    Returns a dict with success flag plus individual operation responses.
    """
    github_api_fn = os.environ.get("GITHUB_API_FUNCTION_NAME")
    if not github_api_fn:
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
            invoke_lambda(github_api_fn, branch_payload)
        )
        operations["create_branch"] = branch_resp
        if branch_resp.get("status") != "success":
            return {
                "success": False,
                "error": branch_resp.get("message", "Branch creation failed"),
                "operations": operations,
            }

        file_payload = {
            "operation": "create_file",
            "owner": owner,
            "repo": repo_name,
            "branch": branch_name,
            "files": [
                {
                    "path": ".github/workflows/ci-cd.yml",
                    "content": yaml_content,
                    "message": "Add CI/CD pipeline workflow",
                }
            ],
        }
        file_resp = _normalize_github_lambda_response(
            invoke_lambda(github_api_fn, file_payload)
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
            "title": f"Add CI/CD pipeline for {repo_name}",
            "head": branch_name,
            "base": base_branch,
            "draft": True,
            "body": (
                "This PR adds a CI/CD pipeline workflow. The pipeline includes build, "
                "test, security scanning, container build, and deployment stages."
            ),
            "files": [],
        }
        pr_resp = _normalize_github_lambda_response(
            invoke_lambda(github_api_fn, pr_payload)
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

    try:
        # Step 1: Repository Scanner Agent
        if "repo_scanner" in agent_ids:
            session_id = f"{task_id}-repo-scanner"
            input_text = f"Analyze repository: {repo_url} (branch: {branch}). Extract all manifest files, detect languages, frameworks, and infrastructure components."

            result = invoke_agent(
                agent_ids["repo_scanner"], AGENT_ALIAS_ID, session_id, input_text
            )
            workflow_steps.append({"step": "repo_scanner", "result": result})

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

        # Step 2: Static Analyzer (Lambda call, not agent)
        static_analyzer_result = None
        if STATIC_ANALYZER_FUNCTION_NAME:
            print(f"Invoking static analyzer: {STATIC_ANALYZER_FUNCTION_NAME}")
            static_analyzer_payload = {
                "repo_url": repo_url,
                "branch": branch,
                "analysis_types": ["dockerfile", "dependencies", "tests"],
            }
            static_analyzer_result = invoke_lambda(
                STATIC_ANALYZER_FUNCTION_NAME, static_analyzer_payload
            )
            workflow_steps.append(
                {"step": "static_analyzer", "result": static_analyzer_result}
            )

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
            repo_analysis = workflow_steps[0].get("result", {}).get("completion", "")
            input_text = f"Based on this repository analysis: {repo_analysis}, design a CI/CD pipeline with appropriate stages for build, test, scan, container build, ECR push, and ECS deployment."

            result = invoke_agent(
                agent_ids["pipeline_designer"], AGENT_ALIAS_ID, session_id, input_text
            )
            workflow_steps.append({"step": "pipeline_designer", "result": result})

        # Step 4: Security & Compliance Agent
        if "security_compliance" in agent_ids:
            session_id = f"{task_id}-security-compliance"
            pipeline_design = workflow_steps[-1].get("result", {}).get("completion", "")
            input_text = f"Review this pipeline design for security and compliance: {pipeline_design}. Ensure SAST/SCA scanning, secrets scanning, and least privilege IAM permissions."

            # Include static analyzer results if available (even if status is not success, include what we have)
            analysis_context = ""
            if static_analyzer_result:
                if static_analyzer_result.get("status") == "success":
                    analysis_context = f"\n\nStatic Analysis Results:\n{json.dumps(static_analyzer_result, indent=2)}"
                else:
                    # Include error information so agent knows static analysis failed
                    analysis_context = f"\n\nNote: Static analysis encountered an issue: {static_analyzer_result.get('message', 'Unknown error')}. Please proceed with security review based on the pipeline design."

            result = invoke_agent(
                agent_ids["security_compliance"],
                AGENT_ALIAS_ID,
                session_id,
                input_text + analysis_context,
            )
            workflow_steps.append({"step": "security_compliance", "result": result})

            if result.get("status") != "success":
                print(
                    f"Warning: Security & Compliance agent returned: {result.get('status')}"
                )
                print(f"Error message: {result.get('message', 'No error message')}")

        # Step 5: YAML Generator Agent
        if "yaml_generator" in agent_ids:
            session_id = f"{task_id}-yaml-generator"
            pipeline_design = workflow_steps[-1].get("result", {}).get("completion", "")
            input_text = f"Generate GitHub Actions workflow YAML based on this pipeline design: {pipeline_design}. Include all stages, proper secrets management, and AWS credentials configuration."

            result = invoke_agent(
                agent_ids["yaml_generator"], AGENT_ALIAS_ID, session_id, input_text
            )
            workflow_steps.append({"step": "yaml_generator", "result": result})

        # Step 6: PR Manager Agent
        if "pr_manager" in agent_ids:
            session_id = f"{task_id}-pr-manager"
            yaml_content = workflow_steps[-1].get("result", {}).get("completion", "")

            # Extract YAML from markdown code blocks if present
            import re

            yaml_match = re.search(
                r"```(?:yaml)?\s*\n(.*?)\n```", yaml_content, re.DOTALL
            )
            if yaml_match:
                yaml_content = yaml_match.group(1)
                print(
                    f"Extracted YAML from markdown code block, length: {len(yaml_content)}"
                )
            else:
                # Try to find YAML-like content (starts with common YAML patterns)
                yaml_lines = []
                in_yaml = False
                for line in yaml_content.split("\n"):
                    if line.strip().startswith(
                        ("name:", "on:", "jobs:", "workflow_dispatch:")
                    ):
                        in_yaml = True
                    if in_yaml:
                        yaml_lines.append(line)
                if yaml_lines:
                    yaml_content = "\n".join(yaml_lines)
                    print(f"Extracted YAML from content, length: {len(yaml_content)}")
                else:
                    print(
                        f"WARNING: Could not extract YAML content. Original content length: {len(yaml_content)}"
                    )
                    print(f"First 500 chars of content: {yaml_content[:500]}")

            # Validate YAML content is not empty
            if not yaml_content or len(yaml_content.strip()) < 50:
                print(
                    f"ERROR: YAML content is too short or empty. Length: {len(yaml_content) if yaml_content else 0}"
                )
                update_task_status(
                    task_id,
                    "failed",
                    {
                        "error": "YAML content is empty or too short",
                        "step": "pr_manager",
                    },
                )
                return {
                    "status": "error",
                    "message": "YAML content is empty or too short",
                    "steps": workflow_steps,
                }

            # Parse repo URL to get owner and repo
            repo_match = re.search(r"github\.com/([^/]+)/([^/]+)", repo_url)
            owner = repo_match.group(1) if repo_match else "unknown"
            repo_name = repo_match.group(2).rstrip("/") if repo_match else "unknown"

            print(
                f"PR Manager: owner={owner}, repo={repo_name}, yaml_length={len(yaml_content)}"
            )
            print(f"YAML content preview (first 200 chars): {yaml_content[:200]}")

            # Format YAML content for the agent - provide it in a clear, copyable format
            # Use triple backticks to make it clear this is the YAML content
            yaml_section = f"""
```yaml
{yaml_content}
```
"""

            input_text = f"""You are creating a GitHub PR with a CI/CD workflow file. You MUST follow these steps EXACTLY in order. DO NOT skip any step.

REPOSITORY INFORMATION:
- Repository URL: {repo_url}
- Owner: {owner}
- Repo: {repo_name}
- Base branch: main

WORKFLOW YAML CONTENT TO USE:
{yaml_section}

STEP 1: CREATE BRANCH
You MUST call the create_branch operation FIRST. Use these exact parameters:
{{
  "operation": "create_branch",
  "owner": "{owner}",
  "repo": "{repo_name}",
  "branch": "ci-cd/add-pipeline",
  "base_branch": "main"
}}

STEP 2: CREATE WORKFLOW FILE (MANDATORY - DO NOT SKIP)
After step 1 succeeds, you MUST call the create_file operation. Use these exact parameters:
{{
  "operation": "create_file",
  "owner": "{owner}",
  "repo": "{repo_name}",
  "branch": "ci-cd/add-pipeline",
  "files": [
    {{
      "path": ".github/workflows/ci-cd.yml",
      "content": {json.dumps(yaml_content)},
      "message": "Add CI/CD pipeline workflow"
    }}
  ]
}}

STEP 3: CREATE PR
After step 2 succeeds, you MUST call the create_pr operation. Use these exact parameters:
{{
  "operation": "create_pr",
  "owner": "{owner}",
  "repo": "{repo_name}",
  "title": "Add CI/CD pipeline for {repo_name}",
  "head": "ci-cd/add-pipeline",
  "base": "main",
  "draft": true,
  "body": "This PR adds a CI/CD pipeline workflow. The pipeline includes build, test, security scanning, container build, and deployment stages."
}}

CRITICAL REQUIREMENTS:
1. You MUST execute all 3 steps in the exact order shown: create_branch → create_file → create_pr
2. You MUST NOT skip step 2. The create_file operation is MANDATORY.
3. The file path MUST be exactly: .github/workflows/ci-cd.yml
4. Use the YAML content provided above exactly as shown
5. Wait for each operation to complete successfully before proceeding to the next step
6. If any operation fails, report the error and stop - do not continue

IMPORTANT: The create_file operation is available in your action group. You MUST use it to create the workflow file."""

            result = invoke_agent(
                agent_ids["pr_manager"], AGENT_ALIAS_ID, session_id, input_text
            )
            workflow_steps.append({"step": "pr_manager", "result": result})

            # Check what operations the agent actually called
            invocations = result.get("action_group_invocations", [])
            branch_name = "ci-cd/add-pipeline"
            fallback_info = {"used": False}
            fallback_required = False
            fallback_reason = None

            completion_lower = (result.get("completion") or "").lower()

            if invocations:
                print(
                    f"PR Manager agent invoked {len(invocations)} action group operations:"
                )
                for inv in invocations:
                    print(
                        f"  - {inv.get('http_method', 'unknown')} {inv.get('api_path', 'unknown')}"
                    )

                create_file_called = any(
                    inv.get("api_path", "").endswith("/create-file")
                    or "create_file" in str(inv.get("api_path", "")).lower()
                    for inv in invocations
                )
                create_branch_called = any(
                    inv.get("api_path", "").endswith("/create-branch")
                    or "create_branch" in str(inv.get("api_path", "")).lower()
                    for inv in invocations
                )
                create_pr_called = any(
                    inv.get("api_path", "").endswith("/create-pr")
                    or "create_pr" in str(inv.get("api_path", "")).lower()
                    for inv in invocations
                )

                print(
                    f"Operations called: branch={create_branch_called}, file={create_file_called}, pr={create_pr_called}"
                )

                missing_operations = []
                if not create_branch_called:
                    missing_operations.append("create_branch")
                if not create_file_called:
                    missing_operations.append("create_file")
                if not create_pr_called:
                    missing_operations.append("create_pr")

                if missing_operations:
                    fallback_required = True
                    fallback_reason = (
                        f"missing_operations:{','.join(missing_operations)}"
                    )
            else:
                print("WARNING: No action group invocations detected in agent response")
                fallback_required = True
                fallback_reason = "no_action_invocations"

            error_indicators = [
                "cannot complete this task",
                "missing critical operations",
                "not available in my function set",
            ]
            if any(indicator in completion_lower for indicator in error_indicators):
                fallback_required = True
                if not fallback_reason:
                    fallback_reason = "agent_reported_missing_operations"

            if fallback_required:
                print(
                    f"WARNING: PR Manager agent could not execute required operations ({fallback_reason})."
                )
                print("Triggering GitHub API Lambda fallback workflow...")
                fallback_outcome = execute_github_workflow(
                    owner, repo_name, branch_name, yaml_content, base_branch="main"
                )
                fallback_info = {
                    "used": True,
                    "reason": fallback_reason,
                    "outcome": fallback_outcome,
                }
                workflow_steps[-1]["result"]["fallback"] = fallback_info

                if not fallback_outcome.get("success"):
                    error_msg = fallback_outcome.get(
                        "error", "GitHub fallback failed for unknown reasons"
                    )
                    print(f"ERROR: GitHub fallback failed: {error_msg}")
                    update_task_status(
                        task_id,
                        "failed",
                        {
                            "error": f"PR Manager fallback failed: {error_msg}",
                            "step": "pr_manager",
                        },
                    )
                    return {
                        "status": "error",
                        "message": f"PR Manager fallback failed: {error_msg}",
                        "steps": workflow_steps,
                    }
                else:
                    print("SUCCESS: GitHub fallback created branch/file/PR.")
            else:
                workflow_steps[-1]["result"]["fallback"] = fallback_info

            # Don't fail the entire workflow if PR creation fails - it's not critical
            if result.get("status") != "success":
                print(f"Warning: PR Manager agent returned: {result.get('status')}")
                print(f"Error message: {result.get('message', 'No error message')}")
                print("Continuing workflow despite PR creation failure")

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
