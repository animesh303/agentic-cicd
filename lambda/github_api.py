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
    Event: {
        "operation": "create_pr" | "create_file" | "create_branch",
        "owner": "repo-owner",
        "repo": "repo-name",
        "branch": "branch-name",
        "base_branch": "main",
        "title": "PR title",
        "body": "PR description",
        "head": "feature-branch",
        "base": "main",
        "draft": true/false,
        "files": [
            {
                "path": ".github/workflows/ci-cd.yml",
                "content": "workflow yaml content",
                "message": "Add CI/CD pipeline"
            }
        ]
    }
    """
    operation = event.get("operation")

    if not operation:
        return {
            "status": "error",
            "message": "operation is required (create_pr, create_file, create_branch)",
        }

    try:
        token = get_github_token()
        owner = event.get("owner")
        repo = event.get("repo")

        if not owner or not repo:
            return {"status": "error", "message": "owner and repo are required"}

        if operation == "create_branch":
            branch = event.get("branch")
            base_branch = event.get("base_branch", "main")

            if not branch:
                return {"status": "error", "message": "branch is required"}

            success = create_branch(owner, repo, base_branch, branch, token)
            return {"status": "success" if success else "error", "branch": branch}

        elif operation == "create_file":
            files = event.get("files", [])
            branch = event.get("branch", "main")

            if not files:
                return {"status": "error", "message": "files array is required"}

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

            return {"status": "success", "files": results}

        elif operation == "create_pr":
            title = event.get("title")
            body = event.get("body", "")
            head = event.get("head")
            base = event.get("base", "main")
            draft = event.get("draft", True)  # Default to draft for human-in-the-loop

            if not title or not head:
                return {"status": "error", "message": "title and head are required"}

            # Create files first if provided
            files = event.get("files", [])
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

            return {
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

        else:
            return {"status": "error", "message": f"Unknown operation: {operation}"}

    except Exception as e:
        return {"status": "error", "message": str(e)}
