#!/usr/bin/env python3
# Simple repo scanner lambda used by Bedrock agent action group.
# It clones a public repo (or uses a supplied URL), inspects files and returns a JSON summary.

import os
import subprocess
import tempfile
import shutil


def detect_languages(repo_dir):
    langs = set()
    for root, dirs, files in os.walk(repo_dir):
        for f in files:
            if f.endswith(".py"):
                langs.add("python")
            if f == "package.json":
                langs.add("node")
            if f.endswith(".java") or f.endswith(".pom"):
                langs.add("java")
            if f.endswith("Dockerfile") or f == "Dockerfile":
                langs.add("docker")
    return list(langs)


def lambda_handler(event, context):
    # Event expected to include repo_url and optionally branch
    repo_url = event.get("repo_url") or event.get("repo")
    branch = event.get("branch") or "main"
    if not repo_url:
        return {"status": "error", "message": "repo_url required"}

    tmpdir = tempfile.mkdtemp()
    try:
        cmd = ["git", "clone", "--depth", "1", "--branch", branch, repo_url, tmpdir]
        subprocess.check_call(cmd)
        languages = detect_languages(tmpdir)

        # detect dockerfile
        dockerfiles = []
        for root, dirs, files in os.walk(tmpdir):
            for f in files:
                if f.lower().startswith("dockerfile") or f == "Dockerfile":
                    dockerfiles.append(os.path.join(root, f))

        # detect terraform / cloudformation
        infra = []
        for root, dirs, files in os.walk(tmpdir):
            for f in files:
                if f.endswith(".tf"):
                    infra.append("terraform")
                if f.endswith(".yml") or f.endswith(".yaml"):
                    path = os.path.join(root, f)
                    with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                        content = fh.read()
                        if (
                            "AWSTemplateFormatVersion" in content
                            or "Resources:" in content
                        ):
                            infra.append("cloudformation")

        result = {
            "repo_url": repo_url,
            "branch": branch,
            "languages": languages,
            "dockerfiles": dockerfiles,
            "infrastructure": list(set(infra)),
        }
        return result
    except Exception as e:
        return {"status": "error", "message": str(e)}
    finally:
        try:
            shutil.rmtree(tmpdir)
        except Exception:
            pass
