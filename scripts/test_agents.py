#!/usr/bin/env python3
"""
Manual agent test harness to isolate failures outside the orchestrator.
"""
import argparse
import json
import os
import sys
import uuid
from datetime import datetime

import boto3
from botocore.config import Config


AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
AGENT_ALIAS_ID = os.environ.get("AGENT_ALIAS_ID", "TSTALIASID")

BEDROCK_CONFIG = Config(
    read_timeout=300,
    connect_timeout=30,
    retries={"max_attempts": 3, "mode": "standard"},
)
bedrock_client = boto3.client(
    "bedrock-agent-runtime", region_name=AWS_REGION, config=BEDROCK_CONFIG
)
lambda_client = boto3.client("lambda", region_name=AWS_REGION)


def invoke_agent(agent_id: str, prompt: str, session_suffix: str = "manual") -> dict:
    session_id = f"diag-{session_suffix}-{uuid.uuid4()}"
    response = bedrock_client.invoke_agent(
        agentId=agent_id,
        agentAliasId=AGENT_ALIAS_ID,
        sessionId=session_id,
        inputText=prompt,
    )

    completion = []
    action_invocations = []
    for event in response["completion"]:
        if "chunk" in event and "bytes" in event["chunk"]:
            completion.append(event["chunk"]["bytes"].decode("utf-8"))
        if "trace" in event and "tracePart" in event["trace"]:
            trace_part = event["trace"]["tracePart"]
            if "actionGroupInvocationInput" in trace_part:
                invocation = trace_part["actionGroupInvocationInput"]
                action_invocations.append(
                    {
                        "action_group": invocation.get("actionGroupName"),
                        "api_path": invocation.get("apiPath"),
                        "http_method": invocation.get("httpMethod"),
                    }
                )
    return {
        "session_id": session_id,
        "completion": "".join(completion).strip(),
        "action_group_invocations": action_invocations,
    }


def invoke_lambda(function_name: str, payload: dict) -> dict:
    resp = lambda_client.invoke(
        FunctionName=function_name,
        InvocationType="RequestResponse",
        Payload=json.dumps(payload),
    )
    return json.loads(resp["Payload"].read())


def load_agent_ids() -> dict:
    tf_output = json.loads(
        os.popen(
            "cd /Users/animeshnaskar/Projects/Accenture/agentic-cicd && terraform output -json agent_ids_map"
        ).read()
    )
    return tf_output


def run_all_tests(args):
    agent_ids = load_agent_ids()
    repo_url = args.repo
    branch = args.branch

    results = {
        "repo_url": repo_url,
        "branch": branch,
        "timestamp": datetime.utcnow().isoformat(),
    }

    print("\n[1/7] Invoking repo_ingestor Lambda...")
    repo_ingestor_fn = os.environ.get(
        "REPO_INGESTOR_FUNCTION_NAME", f"{args.prefix}-repo-ingestor"
    )
    repo_ingestor_result = invoke_lambda(
        repo_ingestor_fn, {"repo_url": repo_url, "branch": branch}
    )
    results["repo_ingestor"] = repo_ingestor_result
    manifests = repo_ingestor_result.get("manifests", {})
    print(
        f"  Status: {repo_ingestor_result.get('status')} (keys: {list(manifests.keys())})"
    )

    print("[2/7] Testing repo_scanner agent...")
    manifest_summary = json.dumps(manifests, indent=2)
    repo_scanner_prompt = f"""Analyze repository: {repo_url} (branch: {branch}).

Manifest data:
{manifest_summary}

Return a structured JSON summary of languages, build systems, test frameworks, IaC, and deployment targets."""
    repo_scanner_result = invoke_agent(
        agent_ids["repo_scanner"], repo_scanner_prompt, "repo-scanner"
    )
    results["repo_scanner"] = repo_scanner_result
    print(f"  Completion length: {len(repo_scanner_result['completion'])}")

    print("[3/7] Testing pipeline_designer agent...")
    pipeline_prompt = (
        "Design a complete CI/CD pipeline for this repository analysis: "
        f"{repo_scanner_result['completion']}"
    )
    pipeline_result = invoke_agent(
        agent_ids["pipeline_designer"], pipeline_prompt, "pipeline"
    )
    results["pipeline_designer"] = pipeline_result
    print(f"  Completion length: {len(pipeline_result['completion'])}")

    print("[4/7] Invoking static_analyzer Lambda...")
    static_fn = os.environ.get(
        "STATIC_ANALYZER_FUNCTION_NAME", f"{args.prefix}-static-analyzer"
    )
    static_result = invoke_lambda(
        static_fn,
        {
            "repo_url": repo_url,
            "branch": branch,
            "analysis_types": ["dockerfile", "dependencies", "tests"],
        },
    )
    results["static_analyzer"] = static_result
    print(f"  Status: {static_result.get('status')}")

    print("[5/7] Testing security_compliance agent...")
    security_prompt = f"""Review this pipeline design for security and compliance: {pipeline_result['completion']}.

Static analysis results:
{json.dumps(static_result, indent=2)}

Return actionable security recommendations."""
    security_result = invoke_agent(
        agent_ids["security_compliance"], security_prompt, "security"
    )
    results["security_compliance"] = security_result
    print(f"  Completion length: {len(security_result['completion'])}")

    print("[6/7] Testing yaml_generator agent...")
    yaml_prompt = (
        "Generate GitHub Actions workflow YAML for this pipeline design: "
        f"{pipeline_result['completion']} "
        "Include aws-actions/configure-aws-credentials, ECR login, secrets usage, and comments."
    )
    yaml_result = invoke_agent(agent_ids["yaml_generator"], yaml_prompt, "yaml")
    results["yaml_generator"] = yaml_result
    print(f"  Completion length: {len(yaml_result['completion'])}")

    print("[7/7] Testing pr_manager agent (PR body generation)...")
    pr_prompt = f"""You are drafting a pull request description for the following workflow YAML:
```yaml
{yaml_result['completion']}
```
Provide sections for Summary, Testing, Required Secrets/IAM, and Deployment notes."""
    pr_result = invoke_agent(agent_ids["pr_manager"], pr_prompt, "pr")
    results["pr_manager"] = pr_result
    print(f"  Completion length: {len(pr_result['completion'])}")

    output_dir = os.path.join("test_results", "agent_tests")
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(
        output_dir, f"agent_test_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json"
    )
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    print(f"\nDetailed results written to {output_path}")


def main():
    parser = argparse.ArgumentParser(description="Manual agent tester")
    parser.add_argument(
        "--repo",
        default="https://github.com/animesh303/animesh303",
        help="Repository URL to analyze",
    )
    parser.add_argument("--branch", default="main", help="Branch name")
    parser.add_argument(
        "--prefix",
        default=os.environ.get("PROJECT_PREFIX", "bedrock-ci-agent"),
        help="Lambda prefix (defaults to PROJECT_PREFIX env)",
    )
    args = parser.parse_args()
    run_all_tests(args)


if __name__ == "__main__":
    sys.exit(main())
