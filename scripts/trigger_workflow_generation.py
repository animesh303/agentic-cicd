#!/usr/bin/env python3
"""
Python script to trigger GitHub workflow generation for a target repository.
This script can be used programmatically or via prompts in Cursor.
"""

import json
import subprocess
import sys
import re
import time
import random
import string
from datetime import datetime
from typing import Dict, Optional, Tuple

try:
    import boto3
    from botocore.exceptions import ClientError, BotoCoreError
except ImportError:
    print("Error: boto3 is required. Install with: pip install boto3")
    sys.exit(1)


def run_command(cmd: list, capture_output: bool = True) -> Tuple[int, str, str]:
    """Run a shell command and return exit code, stdout, stderr."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=capture_output,
            text=True,
            check=False
        )
        return result.returncode, result.stdout, result.stderr
    except Exception as e:
        return 1, "", str(e)


def get_terraform_outputs() -> Dict:
    """Get Terraform outputs as JSON."""
    exit_code, stdout, stderr = run_command(["terraform", "output", "-json"])
    if exit_code != 0:
        raise Exception(f"Failed to get Terraform outputs: {stderr}")
    return json.loads(stdout)


def validate_repo_url(url: str) -> bool:
    """Validate GitHub repository URL format."""
    patterns = [
        r'^https://github\.com/[^/]+/[^/]+/?$',
        r'^git@github\.com:[^/]+/[^/]+/?$'
    ]
    cleaned = url.rstrip('/').rstrip('.git')
    return any(re.match(pattern, cleaned) for pattern in patterns)


def parse_repo_info(url: str) -> Tuple[str, str]:
    """Extract owner and repo name from GitHub URL."""
    cleaned = url.rstrip('/').rstrip('.git')
    cleaned = cleaned.replace('git@github.com:', '').replace('https://github.com/', '')
    parts = cleaned.split('/')
    if len(parts) != 2:
        raise ValueError(f"Invalid repository URL format: {url}")
    return parts[0], parts[1]


def generate_task_id() -> str:
    """Generate a unique task ID."""
    timestamp = int(time.time())
    random_hex = ''.join(random.choices(string.hexdigits.lower(), k=8))
    return f"workflow-gen-{timestamp}-{random_hex}"


def check_prerequisites() -> Tuple[bool, str]:
    """Check if prerequisites are met."""
    # Check AWS CLI
    exit_code, _, _ = run_command(["aws", "--version"])
    if exit_code != 0:
        return False, "AWS CLI not installed"
    
    # Check AWS credentials
    exit_code, _, stderr = run_command(["aws", "sts", "get-caller-identity"])
    if exit_code != 0:
        return False, f"AWS credentials not configured: {stderr}"
    
    # Check Terraform
    exit_code, _, _ = run_command(["terraform", "version"])
    if exit_code != 0:
        return False, "Terraform not installed"
    
    # Check Terraform outputs
    try:
        get_terraform_outputs()
    except Exception as e:
        return False, f"Terraform outputs not available: {str(e)}. Run 'terraform apply' first."
    
    return True, ""


def trigger_workflow_generation(
    repo_url: str,
    branch: str = "main",
    monitor: bool = False,
    poll_interval: int = 5,
    max_wait: int = 1200
) -> Dict:
    """
    Trigger workflow generation for a repository.
    
    Args:
        repo_url: GitHub repository URL
        branch: Branch name (default: "main")
        monitor: Whether to monitor progress (default: False)
        poll_interval: Seconds between polls (default: 5)
        max_wait: Maximum seconds to wait (default: 1200 = 20 minutes)
    
    Returns:
        Dictionary with task_id, status, and result information
    """
    # Validate repository URL
    if not validate_repo_url(repo_url):
        raise ValueError(
            f"Invalid GitHub repository URL: {repo_url}\n"
            "Expected format: https://github.com/owner/repo or git@github.com:owner/repo"
        )
    
    # Get Terraform outputs
    print("Retrieving infrastructure information...")
    outputs = get_terraform_outputs()
    
    lambda_orchestrator = outputs.get("lambda_orchestrator", {}).get("value")
    if not lambda_orchestrator:
        raise Exception("Orchestrator Lambda name not found in Terraform outputs")
    
    agent_ids_map = outputs.get("agent_ids_map", {}).get("value", {})
    if not agent_ids_map:
        raise Exception("Agent IDs not found in Terraform outputs")
    
    dynamodb_table = outputs.get("dynamodb_table", {}).get("value")
    if not dynamodb_table:
        raise Exception("DynamoDB table name not found in Terraform outputs")
    
    # Generate task ID
    task_id = generate_task_id()
    
    # Create payload
    payload = {
        "task_id": task_id,
        "repo_url": repo_url,
        "branch": branch,
        "agent_ids": agent_ids_map
    }
    
    print(f"\nTask ID: {task_id}")
    print(f"Repository: {repo_url}")
    print(f"Branch: {branch}")
    print(f"Orchestrator Lambda: {lambda_orchestrator}")
    
    # Invoke Lambda
    print("\nInvoking orchestrator Lambda...")
    lambda_client = boto3.client("lambda")
    
    try:
        response = lambda_client.invoke(
            FunctionName=lambda_orchestrator,
            InvocationType="Event",
            Payload=json.dumps(payload)
        )
        
        status_code = response["StatusCode"]
        if status_code != 202:
            raise Exception(f"Lambda invocation returned status code {status_code}")
        
        print("✓ Orchestrator Lambda invoked successfully")
        print(f"\nWorkflow generation started. This may take 5-15 minutes.")
        print(f"Task ID for tracking: {task_id}")
        
        result = {
            "task_id": task_id,
            "repo_url": repo_url,
            "branch": branch,
            "status": "invoked",
            "dynamodb_table": dynamodb_table
        }
        
        # Monitor progress if requested
        if monitor:
            print("\nMonitoring progress...")
            final_status = monitor_progress(
                dynamodb_table, task_id, poll_interval, max_wait
            )
            result["final_status"] = final_status
        else:
            print(f"\nTo monitor progress, check DynamoDB table: {dynamodb_table}")
            print(f"Query key: task_id = {task_id}")
        
        return result
        
    except ClientError as e:
        error_code = e.response.get("Error", {}).get("Code", "Unknown")
        error_msg = e.response.get("Error", {}).get("Message", str(e))
        raise Exception(f"AWS Lambda invocation failed: {error_code} - {error_msg}")
    except BotoCoreError as e:
        raise Exception(f"AWS client error: {str(e)}")


def monitor_progress(
    table_name: str,
    task_id: str,
    poll_interval: int = 5,
    max_wait: int = 1200
) -> Dict:
    """Monitor task progress in DynamoDB."""
    dynamodb = boto3.resource("dynamodb")
    table = dynamodb.Table(table_name)
    
    start_time = time.time()
    elapsed = 0
    
    print("\nPolling DynamoDB for task progress...")
    print("Press Ctrl+C to stop monitoring (workflow will continue)\n")
    
    try:
        while elapsed < max_wait:
            try:
                response = table.get_item(Key={"task_id": task_id})
                
                if "Item" in response:
                    item = response["Item"]
                    status = item.get("status", "unknown")
                    result_str = item.get("result", "{}")
                    
                    # Parse result if it's a string
                    if isinstance(result_str, str):
                        try:
                            result = json.loads(result_str)
                        except json.JSONDecodeError:
                            result = {}
                    else:
                        result = result_str
                    
                    # Display status
                    elapsed_seconds = int(time.time() - start_time)
                    elapsed_min = elapsed_seconds // 60
                    elapsed_sec = elapsed_seconds % 60
                    
                    print(f"\rStatus: {status} | Elapsed: {elapsed_min}m {elapsed_sec}s", end="", flush=True)
                    
                    # Check if complete
                    if status in ["completed", "failed"]:
                        print("\n")
                        return {
                            "status": status,
                            "result": result,
                            "elapsed_seconds": elapsed_seconds
                        }
                    
                    # Display steps if available
                    if "steps" in result:
                        steps = result["steps"]
                        completed = sum(1 for s in steps if s.get("result", {}).get("status") == "success")
                        total = len(steps)
                        print(f" | Steps: {completed}/{total} completed", end="", flush=True)
                
                time.sleep(poll_interval)
                elapsed = int(time.time() - start_time)
                
            except KeyboardInterrupt:
                print("\n\nMonitoring stopped. Workflow will continue in background.")
                return {"status": "monitoring_stopped"}
            except Exception as e:
                print(f"\nError polling DynamoDB: {e}")
                time.sleep(poll_interval)
                elapsed = int(time.time() - start_time)
        
        print(f"\n\nMaximum wait time ({max_wait}s) reached. Task may still be in progress.")
        return {"status": "timeout"}
        
    except Exception as e:
        return {"status": "error", "error": str(e)}


def main():
    """Main entry point for command-line usage."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Trigger GitHub workflow generation for a repository"
    )
    parser.add_argument(
        "repo_url",
        help="GitHub repository URL (e.g., https://github.com/owner/repo)"
    )
    parser.add_argument(
        "--branch",
        default="main",
        help="Branch name (default: main)"
    )
    parser.add_argument(
        "--monitor",
        action="store_true",
        help="Monitor progress until completion"
    )
    parser.add_argument(
        "--poll-interval",
        type=int,
        default=5,
        help="Seconds between progress polls (default: 5)"
    )
    parser.add_argument(
        "--max-wait",
        type=int,
        default=1200,
        help="Maximum seconds to wait when monitoring (default: 1200)"
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Only check prerequisites, don't trigger workflow"
    )
    
    args = parser.parse_args()
    
    # Check prerequisites
    print("Checking prerequisites...")
    success, error = check_prerequisites()
    if not success:
        print(f"Error: {error}")
        sys.exit(1)
    print("✓ Prerequisites met")
    
    if args.check_only:
        print("\nPrerequisites check passed. Ready to trigger workflow generation.")
        sys.exit(0)
    
    # Trigger workflow generation
    try:
        result = trigger_workflow_generation(
            repo_url=args.repo_url,
            branch=args.branch,
            monitor=args.monitor,
            poll_interval=args.poll_interval,
            max_wait=args.max_wait
        )
        
        print("\n" + "="*60)
        print("Workflow Generation Triggered Successfully")
        print("="*60)
        print(json.dumps(result, indent=2))
        
    except Exception as e:
        print(f"\nError: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()

