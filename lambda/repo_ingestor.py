#!/usr/bin/env python3
"""
Repository Ingestor Lambda
Downloads repository and extracts manifest files (Dockerfile, package.json, pom.xml, Terraform, CloudFormation, Helm, K8s manifests)
Uses GitHub API to download repos as ZIP files (no git required)
"""
import json
import os
import tempfile
import shutil
import zipfile
import requests


def extract_manifest_content(file_path):
    """Extract content from manifest files"""
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except Exception:
        return None


def download_repo_as_zip(repo_url, branch, tmpdir):
    """
    Download a GitHub repository as a ZIP file and extract it.
    Supports both https://github.com/owner/repo and github.com/owner/repo formats.
    """
    try:
        # Parse GitHub URL
        if repo_url.startswith("https://"):
            repo_url = repo_url.replace("https://", "")
        elif repo_url.startswith("http://"):
            repo_url = repo_url.replace("http://", "")
        
        if repo_url.startswith("github.com/"):
            repo_path = repo_url.replace("github.com/", "")
        elif "/" in repo_url:
            repo_path = repo_url
        else:
            raise ValueError(f"Invalid repository URL format: {repo_url}")
        
        # Remove .git suffix if present
        if repo_path.endswith(".git"):
            repo_path = repo_path[:-4]
        
        # Construct GitHub API URL for zip download
        # Format: https://api.github.com/repos/{owner}/{repo}/zipball/{ref}
        zip_url = f"https://api.github.com/repos/{repo_path}/zipball/{branch}"
        
        # Download the zip file
        print(f"Downloading repository from: {zip_url}")
        response = requests.get(zip_url, stream=True, timeout=60)
        response.raise_for_status()
        
        # Save to temporary zip file
        zip_path = os.path.join(tmpdir, "repo.zip")
        with open(zip_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        
        # Extract zip file
        extract_dir = os.path.join(tmpdir, "extracted")
        os.makedirs(extract_dir, exist_ok=True)
        
        with zipfile.ZipFile(zip_path, "r") as zip_ref:
            zip_ref.extractall(extract_dir)
        
        # Find the actual repo directory (GitHub adds owner-repo-hash prefix)
        extracted_dirs = [d for d in os.listdir(extract_dir) if os.path.isdir(os.path.join(extract_dir, d))]
        if not extracted_dirs:
            raise Exception("No directory found in extracted zip file")
        
        actual_repo_dir = os.path.join(extract_dir, extracted_dirs[0])
        # Move contents to tmpdir root
        for item in os.listdir(actual_repo_dir):
            src = os.path.join(actual_repo_dir, item)
            dst = os.path.join(tmpdir, item)
            if os.path.exists(dst):
                if os.path.isdir(dst):
                    shutil.rmtree(dst)
                else:
                    os.remove(dst)
            shutil.move(src, dst)
        
        # Clean up
        if os.path.exists(zip_path):
            os.remove(zip_path)
        shutil.rmtree(extract_dir, ignore_errors=True)
        
        return tmpdir
        
    except Exception as e:
        raise Exception(f"Failed to download repository: {str(e)}")


def lambda_handler(event, context):
    """
    Handle both direct invocation and Bedrock agent invocation formats.

    Direct invocation:
    {
        "repo_url": "https://github.com/owner/repo",
        "branch": "main"
    }

    Bedrock agent invocation (actual format):
    {
        "messageVersion": "1.0",
        "actionGroup": "repo-ingestor-action",
        "apiPath": "/invoke",
        "httpMethod": "POST",
        "requestBody": {
            "content": {
                "application/json": {
                    "properties": [
                        {"name": "repo_url", "type": "string", "value": "https://github.com/owner/repo"},
                        {"name": "branch", "type": "string", "value": "main"}
                    ]
                }
            }
        }
    }
    """
    # Initialize variables
    action_group = None
    api_path = None
    http_method = None

    # Handle Bedrock agent invocation format
    # Bedrock sends events with messageVersion, actionGroup, requestBody, etc.
    if "messageVersion" in event and "actionGroup" in event:
        # Extract parameters from requestBody.properties array
        request_body = event.get("requestBody", {})
        content = request_body.get("content", {})
        json_content = content.get("application/json", {})
        properties = json_content.get("properties", [])

        # Convert properties array to dict
        body_data = {}
        for prop in properties:
            name = prop.get("name")
            value = prop.get("value")
            if name and value is not None:
                body_data[name] = value

        repo_url = body_data.get("repo_url") or body_data.get("repo")
        branch = body_data.get("branch", "main")

        action_group = event.get("actionGroup", "unknown")
        api_path = event.get("apiPath", "/invoke")
        http_method = event.get("httpMethod", "POST")
    elif "actionGroupInvocationInput" in event:
        # Alternative format (if used)
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
                        },
                    },
                },
            }
        action_group = action_input.get("actionGroupName", "unknown")
        api_path = action_input.get("apiPath", "/invoke")
        http_method = action_input.get("httpMethod", "POST")
    else:
        # Handle direct invocation format
        repo_url = event.get("repo_url") or event.get("repo")
        branch = event.get("branch", "main")

    if not repo_url:
        error_response = {"status": "error", "message": "repo_url required"}
        # Return in Bedrock format if invoked by agent
        if action_group:
            return {
                "messageVersion": "1.0",
                "response": {
                    "actionGroup": action_group,
                    "apiPath": api_path or "/invoke",
                    "httpMethod": http_method or "POST",
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
        # Download repository as ZIP (no git required)
        download_repo_as_zip(repo_url, branch, tmpdir)

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
        if action_group:
            return {
                "messageVersion": "1.0",
                "response": {
                    "actionGroup": action_group,
                    "apiPath": api_path or "/invoke",
                    "httpMethod": http_method or "POST",
                    "httpStatusCode": 200,
                    "responseBody": {"application/json": {"body": json.dumps(result)}},
                },
            }

        return result

    except Exception as e:
        error_message = str(e)
        print(f"Error in repo_ingestor: {error_message}")
        import traceback
        print(f"Traceback: {traceback.format_exc()}")
        error_result = {"status": "error", "message": error_message}

        # Return in Bedrock format if invoked by agent
        if action_group:
            return {
                "messageVersion": "1.0",
                "response": {
                    "actionGroup": action_group,
                    "apiPath": api_path or "/invoke",
                    "httpMethod": http_method or "POST",
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
