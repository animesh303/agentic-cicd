#!/usr/bin/env python3
"""
GitHub API Lambda
Handles GitHub API operations: PR creation, file creation/updates, branch management
Supports draft PRs for human-in-the-loop workflow
"""
import base64
import json
import os
import boto3
import requests
from typing import Dict

secrets_manager = boto3.client("secretsmanager")


def get_github_token():
    """Retrieve GitHub PAT from Secrets Manager"""
    secret_name = os.environ.get("GITHUB_PAT_SECRET_NAME", "bedrock/github/pat")
    try:
        response = secrets_manager.get_secret_value(SecretId=secret_name)
        secret = json.loads(response["SecretString"])
        return secret.get("token")
    except Exception as e:
        raise Exception(f"Failed to retrieve GitHub token: {str(e)}")


def create_branch(
    owner: str, repo: str, base_branch: str, new_branch: str, token: str
) -> bool:
    """Create a new branch from base branch"""
    try:
        # Get SHA of base branch
        url = f"https://api.github.com/repos/{owner}/{repo}/git/ref/heads/{base_branch}"
        headers = {
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json",
        }
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        base_sha = response.json()["object"]["sha"]

        # Create new branch
        url = f"https://api.github.com/repos/{owner}/{repo}/git/refs"
        data = {"ref": f"refs/heads/{new_branch}", "sha": base_sha}
        response = requests.post(url, headers=headers, json=data)

        # Branch might already exist, which is OK
        if response.status_code == 201 or response.status_code == 422:
            return True
        response.raise_for_status()
        return True
    except Exception as e:
        print(f"Error creating branch: {e}")
        return False


def create_or_update_file(
    owner: str,
    repo: str,
    branch: str,
    path: str,
    content: str,
    message: str,
    token: str,
) -> bool:
    """Create or update a file in the repository"""
    try:
        url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}"
        headers = {
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json",
        }

        # Check if file exists
        response = requests.get(url, headers=headers, params={"ref": branch})
        sha = None
        if response.status_code == 200:
            sha = response.json().get("sha")

        # Create or update file
        encoded_content = base64.b64encode(content.encode("utf-8")).decode("utf-8")

        data = {"message": message, "content": encoded_content, "branch": branch}
        if sha:
            data["sha"] = sha

        response = requests.put(url, headers=headers, json=data)
        response.raise_for_status()
        return True
    except Exception as e:
        print(f"Error creating/updating file: {e}")
        return False


def create_pull_request(
    owner: str,
    repo: str,
    title: str,
    body: str,
    head: str,
    base: str,
    draft: bool,
    token: str,
) -> Dict:
    """Create a pull request (draft or ready)"""
    try:
        url = f"https://api.github.com/repos/{owner}/{repo}/pulls"
        headers = {
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json",
        }

        data = {
            "title": title,
            "body": body,
            "head": head,
            "base": base,
            "draft": draft,
        }

        response = requests.post(url, headers=headers, json=data)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"Error creating PR: {e}")
        raise


def lambda_handler(event, context):
    """
    Handle both direct invocation and Bedrock agent invocation formats.

    Direct invocation:
    {
        "operation": "create_pr" | "create_file" | "create_branch",
        "owner": "repo-owner",
        "repo": "repo-name",
        "title": "PR title",
        "head": "feature-branch",
        ...
    }

    Bedrock agent invocation:
    {
        "messageVersion": "1.0",
        "actionGroup": "...",
        "apiPath": "/create-pr",
        "httpMethod": "POST",
        "requestBody": {
            "content": {
                "application/json": {
                    "properties": [
                        {"name": "operation", "value": "create_pr"},
                        {"name": "owner", "value": "..."},
                        ...
                    ]
                }
            }
        }
    }
    """
    # Initialize variables for Bedrock format
    action_group = None
    api_path = None
    http_method = None

    # Handle Bedrock agent invocation format
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

        # Extract all fields from body_data
        operation = body_data.get("operation")
        owner = body_data.get("owner")
        repo = body_data.get("repo")
        branch = body_data.get("branch")
        base_branch = body_data.get("base_branch", "main")
        title = body_data.get("title")
        body = body_data.get("body", "")
        head = body_data.get("head")
        base = body_data.get("base", "main")
        draft = body_data.get("draft", True)
        files = body_data.get("files", [])

        # Handle files if it's a string (JSON string)
        if isinstance(files, str):
            try:
                files = json.loads(files)
            except:
                files = []

        action_group = event.get("actionGroup", "unknown")
        api_path = event.get("apiPath", "/create-pr")
        http_method = event.get("httpMethod", "POST")
    elif "actionGroupInvocationInput" in event:
        # Alternative Bedrock format
        action_input = event["actionGroupInvocationInput"]
        request_body = (
            action_input.get("requestBody", {})
            .get("content", {})
            .get("application/json", {})
        )
        body_str = request_body.get("body", "{}")

        try:
            body_data = json.loads(body_str) if isinstance(body_str, str) else body_str
            operation = body_data.get("operation")
            owner = body_data.get("owner")
            repo = body_data.get("repo")
            branch = body_data.get("branch")
            base_branch = body_data.get("base_branch", "main")
            title = body_data.get("title")
            body = body_data.get("body", "")
            head = body_data.get("head")
            base = body_data.get("base", "main")
            draft = body_data.get("draft", True)
            files = body_data.get("files", [])
        except Exception as e:
            error_response = {
                "messageVersion": "1.0",
                "response": {
                    "actionGroup": action_input.get("actionGroupName", "unknown"),
                    "apiPath": action_input.get("apiPath", "/create-pr"),
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
            return error_response

        action_group = action_input.get("actionGroupName", "unknown")
        api_path = action_input.get("apiPath", "/create-pr")
        http_method = action_input.get("httpMethod", "POST")
    else:
        # Handle direct invocation format
        operation = event.get("operation")
        owner = event.get("owner")
        repo = event.get("repo")
        branch = event.get("branch")
        base_branch = event.get("base_branch", "main")
        title = event.get("title")
        body = event.get("body", "")
        head = event.get("head")
        base = event.get("base", "main")
        draft = event.get("draft", True)
        files = event.get("files", [])

    if not operation:
        error_response = {
            "status": "error",
            "message": "operation is required (create_pr, create_file, create_branch)",
        }
        # Return in Bedrock format if invoked by agent
        if action_group:
            return {
                "messageVersion": "1.0",
                "response": {
                    "actionGroup": action_group,
                    "apiPath": api_path or "/create-pr",
                    "httpMethod": http_method or "POST",
                    "httpStatusCode": 400,
                    "responseBody": {
                        "application/json": {"body": json.dumps(error_response)}
                    },
                },
            }
        return error_response

    try:
        token = get_github_token()

        if not owner or not repo:
            error_response = {
                "status": "error",
                "message": "owner and repo are required",
            }
            # Return in Bedrock format if invoked by agent
            if action_group:
                return {
                    "messageVersion": "1.0",
                    "response": {
                        "actionGroup": action_group,
                        "apiPath": api_path or "/create-pr",
                        "httpMethod": http_method or "POST",
                        "httpStatusCode": 400,
                        "responseBody": {
                            "application/json": {"body": json.dumps(error_response)}
                        },
                    },
                }
            return error_response

        if operation == "create_branch":
            if not branch:
                error_response = {"status": "error", "message": "branch is required"}
                if action_group:
                    return {
                        "messageVersion": "1.0",
                        "response": {
                            "actionGroup": action_group,
                            "apiPath": api_path or "/create-pr",
                            "httpMethod": http_method or "POST",
                            "httpStatusCode": 400,
                            "responseBody": {
                                "application/json": {"body": json.dumps(error_response)}
                            },
                        },
                    }
                return error_response

            success = create_branch(owner, repo, base_branch or "main", branch, token)
            result = {"status": "success" if success else "error", "branch": branch}

            # Return in Bedrock format if invoked by agent
            if action_group:
                return {
                    "messageVersion": "1.0",
                    "response": {
                        "actionGroup": action_group,
                        "apiPath": api_path or "/create-pr",
                        "httpMethod": http_method or "POST",
                        "httpStatusCode": 200 if success else 500,
                        "responseBody": {
                            "application/json": {"body": json.dumps(result)}
                        },
                    },
                }
            return result

        elif operation == "create_file":
            if not files:
                error_response = {
                    "status": "error",
                    "message": "files array is required",
                }
                if action_group:
                    return {
                        "messageVersion": "1.0",
                        "response": {
                            "actionGroup": action_group,
                            "apiPath": api_path or "/create-pr",
                            "httpMethod": http_method or "POST",
                            "httpStatusCode": 400,
                            "responseBody": {
                                "application/json": {"body": json.dumps(error_response)}
                            },
                        },
                    }
                return error_response

            if not branch:
                branch = "main"

            results = []
            for file_info in files:
                path = file_info.get("path")
                content = file_info.get("content")
                message = file_info.get("message", f"Add {path}")

                if not path or content is None:
                    results.append(
                        {
                            "path": path,
                            "status": "error",
                            "message": "path and content required",
                        }
                    )
                    continue

                success = create_or_update_file(
                    owner, repo, branch, path, content, message, token
                )
                results.append(
                    {"path": path, "status": "success" if success else "error"}
                )

            result = {"status": "success", "files": results}

            # Return in Bedrock format if invoked by agent
            if action_group:
                return {
                    "messageVersion": "1.0",
                    "response": {
                        "actionGroup": action_group,
                        "apiPath": api_path or "/create-pr",
                        "httpMethod": http_method or "POST",
                        "httpStatusCode": 200,
                        "responseBody": {
                            "application/json": {"body": json.dumps(result)}
                        },
                    },
                }
            return result

        elif operation == "create_pr":
            if not title or not head:
                error_response = {
                    "status": "error",
                    "message": "title and head are required",
                }
                if action_group:
                    return {
                        "messageVersion": "1.0",
                        "response": {
                            "actionGroup": action_group,
                            "apiPath": api_path or "/create-pr",
                            "httpMethod": http_method or "POST",
                            "httpStatusCode": 400,
                            "responseBody": {
                                "application/json": {"body": json.dumps(error_response)}
                            },
                        },
                    }
                return error_response

            # Create files first if provided
            branch = head

            if files:
                # Ensure branch exists
                create_branch(owner, repo, base, branch, token)

                # Create/update files
                for file_info in files:
                    path = file_info.get("path")
                    content = file_info.get("content")
                    message = file_info.get("message", f"Add {path}")

                    if path and content is not None:
                        create_or_update_file(
                            owner, repo, branch, path, content, message, token
                        )

            # Create PR
            pr = create_pull_request(owner, repo, title, body, head, base, draft, token)

            result = {
                "status": "success",
                "pr_number": pr.get("number"),
                "pr_url": pr.get("html_url"),
                "draft": draft,
                "pr": {
                    "id": pr.get("id"),
                    "number": pr.get("number"),
                    "url": pr.get("html_url"),
                    "state": pr.get("state"),
                    "draft": pr.get("draft"),
                },
            }

            # Return in Bedrock format if invoked by agent
            if action_group:
                return {
                    "messageVersion": "1.0",
                    "response": {
                        "actionGroup": action_group,
                        "apiPath": api_path or "/create-pr",
                        "httpMethod": http_method or "POST",
                        "httpStatusCode": 200,
                        "responseBody": {
                            "application/json": {"body": json.dumps(result)}
                        },
                    },
                }
            return result

        else:
            error_response = {
                "status": "error",
                "message": f"Unknown operation: {operation}",
            }
            if action_group:
                return {
                    "messageVersion": "1.0",
                    "response": {
                        "actionGroup": action_group,
                        "apiPath": api_path or "/create-pr",
                        "httpMethod": http_method or "POST",
                        "httpStatusCode": 400,
                        "responseBody": {
                            "application/json": {"body": json.dumps(error_response)}
                        },
                    },
                }
            return error_response

    except Exception as e:
        error_response = {"status": "error", "message": str(e)}
        if action_group:
            return {
                "messageVersion": "1.0",
                "response": {
                    "actionGroup": action_group,
                    "apiPath": api_path or "/create-pr",
                    "httpMethod": http_method or "POST",
                    "httpStatusCode": 500,
                    "responseBody": {
                        "application/json": {"body": json.dumps(error_response)}
                    },
                },
            }
        return error_response
