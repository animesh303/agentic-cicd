#!/bin/bash
# Update all Bedrock agents with compliant instructions

AGENTS=(
  "repo_scanner:XXKUPYHTWM"
  "pipeline_designer:C4JVO9HIJC"
  "security_compliance:7QPAVZUU9U"
  "yaml_generator:CN0XA2K5QB"
  "pr_manager:8UOGAI8ZQO"
  "feedback:244LZBXL4Q"
)

for agent_info in "${AGENTS[@]}"; do
  IFS=':' read -r name id <<< "$agent_info"
  echo "Updating $name agent ($id)..."
  
  # Get current agent config
  CURRENT=$(aws bedrock-agent get-agent --agent-id "$id" --region us-east-1 --output json 2>/dev/null)
  
  if [ $? -eq 0 ]; then
    # Update with new instruction (add explicit prohibition)
    INSTRUCTION=$(echo "$CURRENT" | jq -r '.instruction' | sed 's/$/\n\nIMPORTANT: Do not use thinking tags or chain-of-thought reasoning. Provide direct answers only./')
    
    aws bedrock-agent update-agent \
      --agent-id "$id" \
      --instruction "$INSTRUCTION" \
      --region us-east-1 \
      --output json > /tmp/update_${name}.json 2>&1
    
    if [ $? -eq 0 ]; then
      echo "  ✓ Updated"
      echo "  Preparing agent..."
      aws bedrock-agent prepare-agent --agent-id "$id" --region us-east-1 > /dev/null 2>&1
      echo "  ✓ Prepared"
    else
      echo "  ✗ Failed"
      cat /tmp/update_${name}.json
    fi
  fi
  echo ""
done
