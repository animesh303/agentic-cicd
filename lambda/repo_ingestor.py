#!/usr/bin/env python3
"""
Repository Ingestor Lambda
Clones repository and extracts manifest files (Dockerfile, package.json, pom.xml, Terraform, CloudFormation, Helm, K8s manifests)
"""
import json
import os
import subprocess
import tempfile
import shutil


def extract_manifest_content(file_path):
    """Extract content from manifest files"""
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except Exception:
        return None


def lambda_handler(event, context):
    """
    Handle both direct invocation and Bedrock agent invocation formats.

    Direct invocation:
    {
        "repo_url": "https://github.com/owner/repo",
        "branch": "main"
    }

    Bedrock agent invocation:
    {
        "actionGroupInvocationInput": {
            "actionGroupName": "repo-ingestor-action",
            "apiPath": "/invoke",
            "httpMethod": "POST",
            "parameters": [],
            "requestBody": {
                "content": {
                    "application/json": {
                        "body": "{\"repo_url\": \"https://github.com/owner/repo\", \"branch\": \"main\"}"
                    }
                }
            }
        }
    }
    """
    # Handle Bedrock agent invocation format
    if "actionGroupInvocationInput" in event:
        action_input = event["actionGroupInvocationInput"]
        request_body = (
            action_input.get("requestBody", {})
            .get("content", {})
            .get("application/json", {})
        )
        body_str = request_body.get("body", "{}")

        try:
            body_data = json.loads(body_str) if isinstance(body_str, str) else body_str
            repo_url = body_data.get("repo_url") or body_data.get("repo")
            branch = body_data.get("branch", "main")
        except Exception as e:
            return {
                "messageVersion": "1.0",
                "response": {
                    "actionGroup": action_input.get("actionGroupName", "unknown"),
                    "apiPath": action_input.get("apiPath", "/invoke"),
                    "httpMethod": action_input.get("httpMethod", "POST"),
                    "httpStatusCode": 400,
                    "responseBody": {
                        "application/json": {
                            "body": json.dumps(
                                {
                                    "status": "error",
                                    "message": f"Invalid request body: {str(e)}",
                                }
                            )
                        }
                    },
                },
            }
    else:
        # Handle direct invocation format
        repo_url = event.get("repo_url") or event.get("repo")
        branch = event.get("branch", "main")

    if not repo_url:
        error_response = {"status": "error", "message": "repo_url required"}
        # Return in Bedrock format if invoked by agent
        if "actionGroupInvocationInput" in event:
            action_input = event["actionGroupInvocationInput"]
            return {
                "messageVersion": "1.0",
                "response": {
                    "actionGroup": action_input.get("actionGroupName", "unknown"),
                    "apiPath": action_input.get("apiPath", "/invoke"),
                    "httpMethod": action_input.get("httpMethod", "POST"),
                    "httpStatusCode": 400,
                    "responseBody": {
                        "application/json": {"body": json.dumps(error_response)}
                    },
                },
            }
        return error_response

    tmpdir = tempfile.mkdtemp()
    manifests = {
        "dockerfiles": [],
        "package_manifests": [],
        "infrastructure": [],
        "kubernetes": [],
        "helm": [],
    }

    try:
        # Clone repository
        cmd = ["git", "clone", "--depth", "1", "--branch", branch, repo_url, tmpdir]
        subprocess.check_call(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        # Walk through repository
        for root, dirs, files in os.walk(tmpdir):
            # Skip .git directory
            dirs[:] = [d for d in dirs if d != ".git"]

            for f in files:
                file_path = os.path.join(root, f)
                rel_path = os.path.relpath(file_path, tmpdir)

                # Dockerfiles
                if f.lower().startswith("dockerfile") or f == "Dockerfile":
                    content = extract_manifest_content(file_path)
                    manifests["dockerfiles"].append(
                        {"path": rel_path, "content": content}
                    )

                # Package manifests
                elif f in [
                    "package.json",
                    "requirements.txt",
                    "pom.xml",
                    "build.gradle",
                    "go.mod",
                    "Cargo.toml",
                ]:
                    content = extract_manifest_content(file_path)
                    manifests["package_manifests"].append(
                        {"path": rel_path, "type": f, "content": content}
                    )

                # Infrastructure as Code
                elif f.endswith(".tf") or f.endswith(".tf.json"):
                    content = extract_manifest_content(file_path)
                    manifests["infrastructure"].append(
                        {"path": rel_path, "type": "terraform", "content": content}
                    )
                elif f.endswith(".yaml") or f.endswith(".yml"):
                    content = extract_manifest_content(file_path)
                    # Check for CloudFormation
                    if "AWSTemplateFormatVersion" in content or "Resources:" in content:
                        manifests["infrastructure"].append(
                            {
                                "path": rel_path,
                                "type": "cloudformation",
                                "content": content,
                            }
                        )
                    # Check for Kubernetes
                    elif "apiVersion" in content and (
                        "kind: Deployment" in content or "kind: Service" in content
                    ):
                        manifests["kubernetes"].append(
                            {"path": rel_path, "content": content}
                        )
                    # Check for Helm
                    elif f == "Chart.yaml" or f == "values.yaml":
                        manifests["helm"].append({"path": rel_path, "content": content})

        result = {
            "status": "success",
            "repo_url": repo_url,
            "branch": branch,
            "manifests": manifests,
        }

        # Return in Bedrock format if invoked by agent
        if "actionGroupInvocationInput" in event:
            action_input = event["actionGroupInvocationInput"]
            return {
                "messageVersion": "1.0",
                "response": {
                    "actionGroup": action_input.get("actionGroupName", "unknown"),
                    "apiPath": action_input.get("apiPath", "/invoke"),
                    "httpMethod": action_input.get("httpMethod", "POST"),
                    "httpStatusCode": 200,
                    "responseBody": {"application/json": {"body": json.dumps(result)}},
                },
            }

        return result

    except Exception as e:
        error_result = {"status": "error", "message": str(e)}

        # Return in Bedrock format if invoked by agent
        if "actionGroupInvocationInput" in event:
            action_input = event["actionGroupInvocationInput"]
            return {
                "messageVersion": "1.0",
                "response": {
                    "actionGroup": action_input.get("actionGroupName", "unknown"),
                    "apiPath": action_input.get("apiPath", "/invoke"),
                    "httpMethod": action_input.get("httpMethod", "POST"),
                    "httpStatusCode": 500,
                    "responseBody": {
                        "application/json": {"body": json.dumps(error_result)}
                    },
                },
            }

        return error_result
    finally:
        try:
            shutil.rmtree(tmpdir)
        except Exception:
            pass
