#!/bin/bash
# Script to update all Bedrock agents to use inference profile
# Usage: ./update_agents.sh

set -e

echo "=========================================="
echo "Updating Bedrock Agents to Inference Profile"
echo "=========================================="
echo ""

# Get agent IDs from Terraform outputs
echo "Getting agent IDs from Terraform..."
REPO_SCANNER=$(terraform output -raw bedrock_agent_repo_scanner_id 2>/dev/null || echo "XXKUPYHTWM")
PIPELINE_DESIGNER=$(terraform output -raw bedrock_agent_pipeline_designer_id 2>/dev/null || echo "C4JVO9HIJC")
SECURITY_COMPLIANCE=$(terraform output -raw bedrock_agent_security_compliance_id 2>/dev/null || echo "7QPAVZUU9U")
YAML_GENERATOR=$(terraform output -raw bedrock_agent_yaml_generator_id 2>/dev/null || echo "CN0XA2K5QB")
PR_MANAGER=$(terraform output -raw bedrock_agent_pr_manager_id 2>/dev/null || echo "8UOGAI8ZQO")
FEEDBACK=$(terraform output -raw bedrock_agent_feedback_id 2>/dev/null || echo "244LZBXL4Q")

AGENTS=(
  "repo_scanner:$REPO_SCANNER"
  "pipeline_designer:$PIPELINE_DESIGNER"
  "security_compliance:$SECURITY_COMPLIANCE"
  "yaml_generator:$YAML_GENERATOR"
  "pr_manager:$PR_MANAGER"
  "feedback:$FEEDBACK"
)

INFERENCE_PROFILE="us.anthropic.claude-3-5-sonnet-20241022-v2:0"
REGION="us-east-1"

echo "Using inference profile: $INFERENCE_PROFILE"
echo "Region: $REGION"
echo ""

for agent_info in "${AGENTS[@]}"; do
  IFS=':' read -r name id <<< "$agent_info"
  echo "Updating $name agent ($id)..."
  
  # Update agent
  if aws bedrock-agent update-agent \
    --agent-id "$id" \
    --foundation-model "$INFERENCE_PROFILE" \
    --region "$REGION" \
    --output json > /tmp/update_result.json 2>&1; then
    
    echo "  ✓ Updated successfully"
    
    # Prepare agent
    echo "  Preparing agent..."
    if aws bedrock-agent prepare-agent --agent-id "$id" --region "$REGION" --output json > /tmp/prepare_result.json 2>&1; then
      echo "  ✓ Prepared successfully"
    else
      echo "  ⚠ Preparation may take time (check status later)"
    fi
  else
    echo "  ✗ Failed to update"
    cat /tmp/update_result.json | jq -r '.message // .' 2>/dev/null || cat /tmp/update_result.json
  fi
  echo ""
done

echo "=========================================="
echo "Update Complete!"
echo "=========================================="
echo ""
echo "Note: Agents may take a few minutes to be ready after preparation."
echo "Verify with: aws bedrock-agent get-agent --agent-id <AGENT_ID> --query 'foundationModel'"
