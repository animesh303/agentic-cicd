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


def invoke_agent(agent_id, agent_alias_id, session_id, input_text):
    """Invoke a Bedrock agent with timeout handling"""
    try:
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
                        print(
                            f"Agent trace: {trace_part.get('agent', {}).get('action', 'unknown')}"
                        )

        print(
            f"Agent {agent_id} completed with {chunk_count} chunks, response length: {len(completion)}"
        )
        return {"status": "success", "completion": completion}
    except Exception as e:
        error_msg = str(e)
        error_type = type(e).__name__
        print(f"Error invoking agent {agent_id} (type: {error_type}): {error_msg}")
        import traceback

        print(f"Traceback: {traceback.format_exc()}")
        return {"status": "error", "message": error_msg, "error_type": error_type}


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
                print(
                    f"Warning: Static analyzer returned: {static_analyzer_result.get('status')}"
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

            # Include static analyzer results if available
            analysis_context = ""
            if (
                static_analyzer_result
                and static_analyzer_result.get("status") == "success"
            ):
                analysis_context = f"\n\nStatic Analysis Results:\n{json.dumps(static_analyzer_result, indent=2)}"

            result = invoke_agent(
                agent_ids["security_compliance"],
                AGENT_ALIAS_ID,
                session_id,
                input_text + analysis_context,
            )
            workflow_steps.append({"step": "security_compliance", "result": result})

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
            input_text = f"Create a GitHub PR for repository {repo_url} with the generated workflow YAML: {yaml_content}. Include a comprehensive description explaining the pipeline stages and required secrets."

            result = invoke_agent(
                agent_ids["pr_manager"], AGENT_ALIAS_ID, session_id, input_text
            )
            workflow_steps.append({"step": "pr_manager", "result": result})

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
