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


def generate_repository_structure(repo_dir, max_depth=3):
    """
    Generate a tree-like representation of repository structure.
    Returns a dictionary with directory structure and key file locations.
    """
    structure = {
        "tree": [],
        "key_paths": {
            "terraform": [],
            "dockerfiles": [],
            "package_manifests": [],
            "kubernetes": [],
            "helm": [],
        },
    }
    
    def build_tree(path, prefix="", depth=0):
        """Recursively build directory tree"""
        if depth > max_depth:
            return []
        
        items = []
        try:
            entries = sorted(os.listdir(path))
            # Filter out hidden files and common ignore patterns
            entries = [
                e
                for e in entries
                if not e.startswith(".")
                and e not in ["__pycache__", "node_modules", ".git"]
            ]
            
            for i, entry in enumerate(entries):
                entry_path = os.path.join(path, entry)
                rel_path = os.path.relpath(entry_path, repo_dir)
                is_last = i == len(entries) - 1
                
                if os.path.isdir(entry_path):
                    items.append(f"{prefix}{'└── ' if is_last else '├── '}{entry}/")
                    extension = "    " if is_last else "│   "
                    items.extend(build_tree(entry_path, prefix + extension, depth + 1))
                else:
                    items.append(f"{prefix}{'└── ' if is_last else '├── '}{entry}")
                    
                    # Track key file types
                    if entry.endswith((".tf", ".tf.json")):
                        structure["key_paths"]["terraform"].append(rel_path)
                    elif entry.lower().startswith("dockerfile") or entry == "Dockerfile":
                        structure["key_paths"]["dockerfiles"].append(rel_path)
                    elif entry in [
                        "package.json",
                        "requirements.txt",
                        "pom.xml",
                        "build.gradle",
                        "go.mod",
                        "Cargo.toml",
                    ]:
                        structure["key_paths"]["package_manifests"].append(rel_path)
                    elif entry.endswith((".yaml", ".yml")):
                        # Check if it's K8s or Helm
                        try:
                            with open(entry_path, "r", encoding="utf-8", errors="ignore") as f:
                                content = f.read()
                                if "apiVersion" in content and ("kind:" in content):
                                    structure["key_paths"]["kubernetes"].append(rel_path)
                                elif entry in ["Chart.yaml", "values.yaml"]:
                                    structure["key_paths"]["helm"].append(rel_path)
                        except:
                            pass
        except PermissionError:
            pass
        
        return items
    
    structure["tree"] = build_tree(repo_dir)
    
    # Determine Terraform working directory (directory containing .tf files)
    terraform_dirs = set()
    for tf_path in structure["key_paths"]["terraform"]:
        dir_path = os.path.dirname(tf_path)
        terraform_dirs.add(dir_path if dir_path else ".")
    
    structure["terraform_working_dir"] = (
        list(terraform_dirs)[0] if len(terraform_dirs) == 1 else "."
    )
    if len(terraform_dirs) > 1:
        # Multiple directories with Terraform files
        structure["terraform_working_dir"] = "."
        structure["terraform_directories"] = sorted(list(terraform_dirs))
    
    return structure


def download_repo_as_zip(repo_url, branch, tmpdir):
    """
    Download a GitHub repository as a ZIP file and extract it.
    Supports both https://github.com/owner/repo and github.com/owner/repo formats.
    """
    try:
        # Parse GitHub URL
        original_url = repo_url
        if repo_url.startswith("https://"):
            repo_url = repo_url.replace("https://", "")
        elif repo_url.startswith("http://"):
            repo_url = repo_url.replace("http://", "")

        if repo_url.startswith("github.com/"):
            repo_path = repo_url.replace("github.com/", "")
        elif "/" in repo_url:
            repo_path = repo_url
        else:
            raise ValueError(f"Invalid repository URL format: {original_url}")

        # Remove .git suffix if present
        if repo_path.endswith(".git"):
            repo_path = repo_path[:-4]

        # Split into owner and repo
        parts = repo_path.split("/")
        if len(parts) != 2:
            raise ValueError(
                f"Invalid repository path format: {repo_path}. Expected 'owner/repo'"
            )

        owner, repo = parts[0], parts[1]

        # Use direct download URL (more reliable than API endpoint)
        # Format: https://github.com/{owner}/{repo}/archive/refs/heads/{branch}.zip
        # This is the standard GitHub archive URL format
        branches_to_try = [branch]

        # Add fallback branches if not already in the list
        if branch.lower() != "main":
            branches_to_try.append("main")
        if branch.lower() != "master":
            branches_to_try.append("master")

        response = None
        zip_url = None

        # Try each branch until one works
        for try_branch in branches_to_try:
            zip_url = (
                f"https://github.com/{owner}/{repo}/archive/refs/heads/{try_branch}.zip"
            )
            print(f"Trying to download: {owner}/{repo} (branch: {try_branch})")
            print(f"URL: {zip_url}")

            response = requests.get(
                zip_url, stream=True, timeout=60, allow_redirects=True
            )

            if response.status_code == 200:
                print(f"✓ Successfully found branch: {try_branch}")
                break
            elif response.status_code == 404:
                print(f"✗ Branch '{try_branch}' not found")
                if try_branch != branches_to_try[-1]:  # Not the last one
                    print("Trying next branch...")
                continue
            else:
                # Some other error, break and handle below
                break

        # Check for errors and provide helpful messages
        if response is None or response.status_code != 200:
            if response is None:
                error_msg = f"Failed to download repository {owner}/{repo}"
            elif response.status_code == 404:
                error_msg = (
                    f"Repository {owner}/{repo} not found or none of the branches exist"
                )
                # Try to get more info from GitHub API
                try:
                    api_url = f"https://api.github.com/repos/{owner}/{repo}"
                    api_response = requests.get(api_url, timeout=10)
                    if api_response.status_code == 404:
                        error_msg = f"Repository {owner}/{repo} not found. It may be private or not exist."
                    elif api_response.status_code == 403:
                        error_msg = f"Repository {owner}/{repo} may be private. Authentication required."
                    elif api_response.status_code == 200:
                        # Repo exists, so branches are wrong
                        repo_data = api_response.json()
                        default_branch = repo_data.get("default_branch", "main")
                        error_msg = f"None of the tried branches exist. Repository exists with default branch: {default_branch}. Tried: {', '.join(branches_to_try)}"
                except Exception as e:
                    print(f"Could not get repository info: {e}")
            else:
                # Other HTTP error
                try:
                    response.raise_for_status()
                except Exception as e:
                    error_msg = f"HTTP error downloading repository: {str(e)}"

            raise Exception(error_msg)

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

        # Find the actual repo directory
        # GitHub archive format: {repo}-{branch} or {repo}-{hash}
        extracted_dirs = [
            d
            for d in os.listdir(extract_dir)
            if os.path.isdir(os.path.join(extract_dir, d))
        ]
        if not extracted_dirs:
            raise Exception("No directory found in extracted zip file")

        # Use the first (and typically only) directory
        actual_repo_dir = os.path.join(extract_dir, extracted_dirs[0])
        print(f"Extracted repository directory: {extracted_dirs[0]}")
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

        # Generate repository structure
        repo_structure = generate_repository_structure(tmpdir)
        
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
            "repository_structure": repo_structure,
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
