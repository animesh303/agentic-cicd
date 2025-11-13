#!/bin/bash
# Fix chain-of-thought instructions in Bedrock agents
# This script updates all agents to explicitly prohibit thinking tags

set -e

echo "=========================================="
echo "Fixing Chain-of-Thought Instructions"
echo "=========================================="
echo ""

# Get agent IDs from Terraform or use defaults
REPO_SCANNER=$(terraform output -raw bedrock_agent_repo_scanner_id 2>/dev/null || echo "XXKUPYHTWM")
PIPELINE_DESIGNER=$(terraform output -raw bedrock_agent_pipeline_designer_id 2>/dev/null || echo "C4JVO9HIJC")
SECURITY_COMPLIANCE=$(terraform output -raw bedrock_agent_security_compliance_id 2>/dev/null || echo "7QPAVZUU9U")
YAML_GENERATOR=$(terraform output -raw bedrock_agent_yaml_generator_id 2>/dev/null || echo "CN0XA2K5QB")
PR_MANAGER=$(terraform output -raw bedrock_agent_pr_manager_id 2>/dev/null || echo "8UOGAI8ZQO")
FEEDBACK=$(terraform output -raw bedrock_agent_feedback_id 2>/dev/null || echo "244LZBXL4Q")

REGION="us-east-1"
PROHIBITION="\n\nIMPORTANT: Do not use thinking tags or chain-of-thought reasoning. Provide direct answers only."

update_agent() {
    local AGENT_ID=$1
    local AGENT_NAME=$2
    
    echo "Updating $AGENT_NAME agent ($AGENT_ID)..."
    
    # Get current instruction
    CURRENT_INSTRUCTION=$(aws bedrock-agent get-agent \
        --agent-id "$AGENT_ID" \
        --region "$REGION" \
        --query 'instruction' \
        --output text 2>/dev/null || echo "")
    
    if [ -z "$CURRENT_INSTRUCTION" ]; then
        echo "  ⚠ Could not retrieve current instruction"
        return 1
    fi
    
    # Check if already has prohibition
    if echo "$CURRENT_INSTRUCTION" | grep -qi "do not use thinking\|chain-of-thought"; then
        echo "  ✓ Already has prohibition statement"
        return 0
    fi
    
    # Add prohibition to instruction
    NEW_INSTRUCTION="${CURRENT_INSTRUCTION}${PROHIBITION}"
    
    # Update agent
    if aws bedrock-agent update-agent \
        --agent-id "$AGENT_ID" \
        --instruction "$NEW_INSTRUCTION" \
        --region "$REGION" \
        --output json > /tmp/update_${AGENT_NAME}.json 2>&1; then
        
        echo "  ✓ Instruction updated"
        
        # Prepare agent
        echo "  Preparing agent..."
        if aws bedrock-agent prepare-agent --agent-id "$AGENT_ID" --region "$REGION" --output json > /tmp/prepare_${AGENT_NAME}.json 2>&1; then
            echo "  ✓ Agent prepared"
        else
            echo "  ⚠ Preparation initiated (may take time)"
        fi
    else
        echo "  ✗ Failed to update"
        cat /tmp/update_${AGENT_NAME}.json | jq -r '.message // .' 2>/dev/null || cat /tmp/update_${AGENT_NAME}.json
        return 1
    fi
    
    echo ""
}

# Update all agents
update_agent "$REPO_SCANNER" "repo_scanner"
update_agent "$PIPELINE_DESIGNER" "pipeline_designer"
update_agent "$SECURITY_COMPLIANCE" "security_compliance"
update_agent "$YAML_GENERATOR" "yaml_generator"
update_agent "$PR_MANAGER" "pr_manager"
update_agent "$FEEDBACK" "feedback"

echo "=========================================="
echo "Update Complete!"
echo "=========================================="
echo ""
echo "Note: Agents may take 2-5 minutes to be ready after preparation."
echo "Test with: aws bedrock-agent-runtime invoke-agent --agent-id <ID> --agent-alias-id TSTALIASID --session-id test-123 --input-text 'Hello' /tmp/test.json"

