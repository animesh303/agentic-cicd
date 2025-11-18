#!/usr/bin/env python3
"""
Template Engine & Validator Lambda
Converts agent output into concrete GitHub Actions YAML using templates and validates syntax
"""
import json
import yaml
import re


class LiteralSafeLoader(yaml.SafeLoader):
    """Safe loader that treats words like 'on'/'off' as plain strings."""


for first_letter, resolvers in list(LiteralSafeLoader.yaml_implicit_resolvers.items()):
    filtered = [
        (tag, regexp) for tag, regexp in resolvers if tag != "tag:yaml.org,2002:bool"
    ]
    LiteralSafeLoader.yaml_implicit_resolvers[first_letter] = filtered


def extract_yaml_content(text):
    """Extract YAML from text (handles fenced code blocks and raw YAML)."""
    if not text:
        return ""
    
    # First, try to extract from fenced code blocks (```yaml ... ```)
    fenced_match = re.search(
        r"```(?:yaml)?\s*\n(.*?)\n```", text, re.DOTALL | re.IGNORECASE
    )
    if fenced_match:
        return fenced_match.group(1).strip()
    
    # If no fenced block, try to extract YAML lines
    # YAML typically starts with "name:", "on:", "jobs:", etc.
    yaml_lines = []
    capturing = False
    for line in text.splitlines():
        stripped = line.strip()
        # Start capturing when we see YAML structure indicators
        if stripped.startswith(("name:", "on:", "jobs:", "workflow_dispatch:", "permissions:")):
            capturing = True
        # Stop capturing when we hit markdown headers or other non-YAML content
        if capturing:
            if stripped.startswith("#") and len(stripped) > 1 and stripped[1] != " ":
                # Markdown header (## Header) - stop here
                break
            if stripped.startswith("##") or (stripped.startswith("#") and ("Required" in stripped or "README" in stripped or "This workflow" in stripped)):
                # Markdown section - stop here
                break
            yaml_lines.append(line)
    
    return "\n".join(yaml_lines).strip()


def validate_yaml_syntax(yaml_content):
    """Validate YAML syntax"""
    errors = []
    warnings = []
    
    # Extract only YAML portion if content includes markdown
    yaml_only = extract_yaml_content(yaml_content)
    if not yaml_only:
        yaml_only = yaml_content  # Fallback to original if extraction fails
        warnings.append("Could not extract YAML from content, validating entire content")

    try:
        parsed = yaml.load(yaml_only, Loader=LiteralSafeLoader)
        if not parsed:
            errors.append("YAML is empty or invalid")
            return {"valid": False, "errors": errors, "warnings": warnings}
    except yaml.YAMLError as e:
        errors.append(f"YAML syntax error: {str(e)}")
        return {"valid": False, "errors": errors, "warnings": warnings}

    # Validate GitHub Actions structure
    if "name" not in parsed:
        warnings.append("Workflow name is missing")

    if "on" not in parsed:
        errors.append('Workflow trigger ("on") is missing')

    if "jobs" not in parsed:
        errors.append("Workflow jobs section is missing")
    else:
        # Validate job structure
        for job_name, job_config in parsed.get("jobs", {}).items():
            if "runs-on" not in job_config:
                errors.append(f'Job "{job_name}" missing "runs-on"')

            if "steps" not in job_config:
                errors.append(f'Job "{job_name}" missing "steps"')
            else:
                # Validate steps
                for i, step in enumerate(job_config["steps"]):
                    if "uses" not in step and "run" not in step:
                        errors.append(
                            f'Job "{job_name}" step {i+1} missing "uses" or "run"'
                        )

    # Check for common security issues (use extracted YAML only)
    yaml_str = yaml_only.lower()
    if "password" in yaml_str or "secret" in yaml_str:
        if "secrets." not in yaml_str and "${{" not in yaml_str:
            warnings.append("Potential hardcoded secrets detected")

    return {"valid": len(errors) == 0, "errors": errors, "warnings": warnings}


def validate_secrets_usage(yaml_content):
    """Check that required secrets are properly referenced"""
    # Extract only YAML portion if content includes markdown
    yaml_only = extract_yaml_content(yaml_content)
    if not yaml_only:
        yaml_only = yaml_content  # Fallback to original if extraction fails
    
    secrets_used = re.findall(r"\$\{\{\s*secrets\.([^\s}]+)\s*\}\}", yaml_only)
    return {
        "secrets_referenced": list(set(secrets_used)),
        "properly_used": len(secrets_used) > 0
        or "secrets." not in yaml_only.lower(),
    }


def validate_permissions(yaml_content):
    """Check IAM permissions and least privilege"""
    warnings = []
    
    # Extract only YAML portion if content includes markdown
    yaml_only = extract_yaml_content(yaml_content)
    if not yaml_only:
        yaml_only = yaml_content  # Fallback to original if extraction fails

    try:
        parsed = yaml.load(yaml_only, Loader=LiteralSafeLoader)
        if not parsed:
            return {"warnings": warnings}
    except yaml.YAMLError as e:
        # If YAML parsing fails, return warnings but don't fail validation
        warnings.append(f"Could not parse YAML for permissions check: {str(e)}")
        return {"warnings": warnings}

    # Check for permissions section
    for job_name, job_config in parsed.get("jobs", {}).items():
        permissions = job_config.get("permissions", {})

        if permissions.get("contents") == "write":
            warnings.append(
                f'Job "{job_name}" has write permissions to contents - ensure this is necessary'
            )

        if permissions.get("id-token") == "write":
            warnings.append(
                f'Job "{job_name}" has OIDC write permissions - verify least privilege'
            )

    return {"warnings": warnings}


def lambda_handler(event, context):
    """
    Handle both direct invocation and Bedrock agent invocation formats.

    Direct invocation:
    {
        "yaml_content": "...",
        "validation_level": "strict" | "normal" | "lenient"
    }

    Bedrock agent invocation:
    {
        "messageVersion": "1.0",
        "actionGroup": "...",
        "apiPath": "/invoke",
        "httpMethod": "POST",
        "requestBody": {
            "content": {
                "application/json": {
                    "properties": [
                        {"name": "yaml_content", "value": "..."},
                        {"name": "validation_level", "value": "normal"}
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

        yaml_content = body_data.get("yaml_content")
        validation_level = body_data.get("validation_level", "normal")

        action_group = event.get("actionGroup", "unknown")
        api_path = event.get("apiPath", "/invoke")
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
            yaml_content = body_data.get("yaml_content")
            validation_level = body_data.get("validation_level", "normal")
        except Exception as e:
            error_response = {
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
            return error_response

        action_group = action_input.get("actionGroupName", "unknown")
        api_path = action_input.get("apiPath", "/invoke")
        http_method = action_input.get("httpMethod", "POST")
    else:
        # Handle direct invocation format
        yaml_content = event.get("yaml_content")
        validation_level = event.get("validation_level", "normal")

    if not yaml_content:
        error_response = {"status": "error", "message": "yaml_content required"}
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

    # Syntax validation
    syntax_result = validate_yaml_syntax(yaml_content)

    # Secrets validation
    secrets_result = validate_secrets_usage(yaml_content)

    # Permissions validation
    permissions_result = validate_permissions(yaml_content)

    # Combine results
    all_errors = syntax_result.get("errors", [])
    all_warnings = syntax_result.get("warnings", []) + permissions_result.get(
        "warnings", []
    )

    # Determine overall validity based on validation level
    is_valid = False
    if validation_level == "strict":
        is_valid = len(all_errors) == 0 and len(all_warnings) == 0
    elif validation_level == "normal":
        is_valid = len(all_errors) == 0
    else:  # lenient
        is_valid = True

    result = {
        "status": "success" if is_valid else "validation_failed",
        "valid": is_valid,
        "syntax": syntax_result,
        "secrets": secrets_result,
        "permissions": permissions_result,
        "summary": {
            "errors": all_errors,
            "warnings": all_warnings,
            "secrets_referenced": secrets_result.get("secrets_referenced", []),
        },
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
