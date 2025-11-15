#!/bin/bash

# Script to check what actions the PR Manager agent actually performed
# by analyzing CloudWatch logs from the orchestrator Lambda

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}Checking PR Manager Agent Actions${NC}"
echo "=========================================="
echo ""

# Get orchestrator function name
ORCHESTRATOR_FN=$(terraform output -raw lambda_orchestrator 2>/dev/null || echo "")

if [ -z "$ORCHESTRATOR_FN" ]; then
    echo -e "${RED}✗ Orchestrator Lambda name not found${NC}"
    exit 1
fi

echo -e "${GREEN}✓ Found Orchestrator: $ORCHESTRATOR_FN${NC}"
echo ""

# Check recent logs for PR Manager activity
echo "Checking recent CloudWatch logs..."
echo ""

# Look for PR Manager invocations
aws logs filter-log-events \
    --log-group-name "/aws/lambda/$ORCHESTRATOR_FN" \
    --filter-pattern "PR Manager" \
    --max-items 20 \
    --output json 2>/dev/null | jq -r '.events[] | "\(.timestamp | strftime("%Y-%m-%d %H:%M:%S")) - \(.message)"' 2>/dev/null || echo "No PR Manager logs found"

echo ""
echo "Checking for action group invocations..."
aws logs filter-log-events \
    --log-group-name "/aws/lambda/$ORCHESTRATOR_FN" \
    --filter-pattern "Action Group Invocation" \
    --max-items 20 \
    --output json 2>/dev/null | jq -r '.events[] | "\(.timestamp | strftime("%Y-%m-%d %H:%M:%S")) - \(.message)"' 2>/dev/null || echo "No action group invocations found"

echo ""
echo "Checking for create_file operations..."
aws logs filter-log-events \
    --log-group-name "/aws/lambda/$ORCHESTRATOR_FN" \
    --filter-pattern "create_file" \
    --max-items 20 \
    --output json 2>/dev/null | jq -r '.events[] | "\(.timestamp | strftime("%Y-%m-%d %H:%M:%S")) - \(.message)"' 2>/dev/null || echo "No create_file operations found"

echo ""
echo "Checking for errors..."
aws logs filter-log-events \
    --log-group-name "/aws/lambda/$ORCHESTRATOR_FN" \
    --filter-pattern "ERROR" \
    --max-items 10 \
    --output json 2>/dev/null | jq -r '.events[] | "\(.timestamp | strftime("%Y-%m-%d %H:%M:%S")) - \(.message)"' 2>/dev/null || echo "No errors found"

echo ""
echo "Checking for PR Manager error details..."
aws logs filter-log-events \
    --log-group-name "/aws/lambda/$ORCHESTRATOR_FN" \
    --filter-pattern "Error message" \
    --max-items 10 \
    --output json 2>/dev/null | jq -r '.events[] | "\(.timestamp | strftime("%Y-%m-%d %H:%M:%S")) - \(.message)"' 2>/dev/null || echo "No error messages found"

echo ""
echo "Checking for agent invocation errors..."
aws logs filter-log-events \
    --log-group-name "/aws/lambda/$ORCHESTRATOR_FN" \
    --filter-pattern "Error invoking agent" \
    --max-items 5 \
    --output json 2>/dev/null | jq -r '.events[] | "\(.timestamp | strftime("%Y-%m-%d %H:%M:%S")) - \(.message)"' 2>/dev/null || echo "No agent invocation errors found"

echo ""
echo "Getting most recent PR Manager error (full context)..."
aws logs filter-log-events \
    --log-group-name "/aws/lambda/$ORCHESTRATOR_FN" \
    --filter-pattern "PR Manager" \
    --max-items 1 \
    --start-time $(($(date +%s) - 86400))000 \
    --output json 2>/dev/null | jq -r '.events[-1].message' 2>/dev/null || echo "No recent PR Manager logs found"

echo ""
echo "=========================================="
echo -e "${BLUE}To see live logs:${NC}"
echo "aws logs tail /aws/lambda/$ORCHESTRATOR_FN --follow"
echo ""

