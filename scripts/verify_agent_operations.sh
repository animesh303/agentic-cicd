#!/bin/bash

# Script to verify that the PR Manager agent can see the new operations
# (create_branch, create_file, create_pr)

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}Verifying PR Manager Agent Operations${NC}"
echo "=========================================="
echo ""

# Get agent ID from Terraform
PR_MANAGER_AGENT_ID=$(terraform output -raw bedrock_agent_pr_manager_id 2>/dev/null || echo "")

if [ -z "$PR_MANAGER_AGENT_ID" ]; then
    echo -e "${RED}✗ PR Manager Agent ID not found in Terraform outputs${NC}"
    echo "Run 'terraform apply' first or check your Terraform state."
    exit 1
fi

echo -e "${GREEN}✓ Found PR Manager Agent ID: $PR_MANAGER_AGENT_ID${NC}"
echo ""

# Get action group ID
echo "Fetching action group information..."
ACTION_GROUP_INFO=$(aws bedrock-agent list-agent-action-groups \
    --agent-id "$PR_MANAGER_AGENT_ID" \
    --agent-version DRAFT \
    --region us-east-1 \
    --output json 2>/dev/null || echo "{}")

if [ "$ACTION_GROUP_INFO" = "{}" ]; then
    echo -e "${RED}✗ Could not fetch action group information${NC}"
    exit 1
fi

ACTION_GROUP_ID=$(echo "$ACTION_GROUP_INFO" | jq -r '.actionGroupSummaries[0].actionGroupId // empty' 2>/dev/null || echo "")

if [ -z "$ACTION_GROUP_ID" ]; then
    echo -e "${RED}✗ Could not find action group ID${NC}"
    exit 1
fi

echo -e "${GREEN}✓ Found Action Group ID: $ACTION_GROUP_ID${NC}"
echo ""

# Get action group details
echo "Fetching action group details..."
ACTION_GROUP_DETAILS=$(aws bedrock-agent get-agent-action-group \
    --agent-id "$PR_MANAGER_AGENT_ID" \
    --agent-version DRAFT \
    --action-group-id "$ACTION_GROUP_ID" \
    --region us-east-1 \
    --output json 2>/dev/null || echo "{}")

# Check if OpenAPI spec is in S3 (from action group or Terraform output)
S3_BUCKET=$(echo "$ACTION_GROUP_DETAILS" | jq -r '.actionGroupExecutor.apiSchema.s3.s3BucketName // empty' 2>/dev/null || echo "")
S3_KEY=$(echo "$ACTION_GROUP_DETAILS" | jq -r '.actionGroupExecutor.apiSchema.s3.s3ObjectKey // empty' 2>/dev/null || echo "")

# If not found in action group, try to get from Terraform
if [ -z "$S3_BUCKET" ] || [ -z "$S3_KEY" ]; then
    echo -e "${YELLOW}⚠ Action group schema not found, checking Terraform S3 bucket...${NC}"
    S3_BUCKET=$(terraform output -raw s3_bucket 2>/dev/null || echo "")
    S3_KEY="openapi/github_pr_tool.yaml"
fi

if [ -n "$S3_BUCKET" ] && [ -n "$S3_KEY" ]; then
    echo -e "${GREEN}✓ Action group uses S3 for OpenAPI spec${NC}"
    echo "  Bucket: $S3_BUCKET"
    echo "  Key: $S3_KEY"
    echo ""
    
    # Check if file exists in S3
    if aws s3 ls "s3://$S3_BUCKET/$S3_KEY" &> /dev/null; then
        echo -e "${GREEN}✓ OpenAPI spec exists in S3${NC}"
        
        # Download and check for operations
        echo "Checking for required operations..."
        aws s3 cp "s3://$S3_BUCKET/$S3_KEY" /tmp/github_pr_tool.yaml &> /dev/null
        
        if grep -q "create_branch" /tmp/github_pr_tool.yaml; then
            echo -e "${GREEN}✓ create_branch operation found${NC}"
        else
            echo -e "${RED}✗ create_branch operation NOT found${NC}"
        fi
        
        if grep -q "create_file" /tmp/github_pr_tool.yaml; then
            echo -e "${GREEN}✓ create_file operation found${NC}"
        else
            echo -e "${RED}✗ create_file operation NOT found${NC}"
        fi
        
        if grep -q "create_pr" /tmp/github_pr_tool.yaml; then
            echo -e "${GREEN}✓ create_pr operation found${NC}"
        else
            echo -e "${RED}✗ create_pr operation NOT found${NC}"
        fi
        
        rm -f /tmp/github_pr_tool.yaml
    else
        echo -e "${RED}✗ OpenAPI spec NOT found in S3${NC}"
        echo "  Run 'terraform apply' to upload the updated spec."
    fi
else
    echo -e "${YELLOW}⚠ Could not determine S3 bucket/key for OpenAPI spec${NC}"
    echo "  Checking if file exists in expected location..."
    
    # Try default location
    S3_BUCKET=$(terraform output -raw s3_bucket 2>/dev/null || echo "")
    if [ -n "$S3_BUCKET" ]; then
        if aws s3 ls "s3://$S3_BUCKET/openapi/github_pr_tool.yaml" &> /dev/null; then
            echo -e "${GREEN}✓ Found OpenAPI spec in S3: s3://$S3_BUCKET/openapi/github_pr_tool.yaml${NC}"
            aws s3 cp "s3://$S3_BUCKET/openapi/github_pr_tool.yaml" /tmp/github_pr_tool.yaml &> /dev/null
            
            echo "Checking for required operations..."
            if grep -q "create_branch" /tmp/github_pr_tool.yaml; then
                echo -e "${GREEN}✓ create_branch operation found${NC}"
            else
                echo -e "${RED}✗ create_branch operation NOT found${NC}"
            fi
            
            if grep -q "create_file" /tmp/github_pr_tool.yaml; then
                echo -e "${GREEN}✓ create_file operation found${NC}"
            else
                echo -e "${RED}✗ create_file operation NOT found${NC}"
            fi
            
            if grep -q "create_pr" /tmp/github_pr_tool.yaml; then
                echo -e "${GREEN}✓ create_pr operation found${NC}"
            else
                echo -e "${RED}✗ create_pr operation NOT found${NC}"
            fi
            
            rm -f /tmp/github_pr_tool.yaml
        else
            echo -e "${RED}✗ OpenAPI spec NOT found in S3${NC}"
            echo "  Expected location: s3://$S3_BUCKET/openapi/github_pr_tool.yaml"
            echo "  Run 'terraform apply' to upload the spec."
        fi
    fi
fi

echo ""
echo "=========================================="
echo -e "${BLUE}Next Steps:${NC}"
echo ""
echo "1. If operations are missing, ensure you've run:"
echo "   terraform apply"
echo ""
echo "2. If operations exist but agent still doesn't use them, prepare the agent:"
echo "   aws bedrock-agent prepare-agent --agent-id $PR_MANAGER_AGENT_ID --region us-east-1"
echo ""
echo "3. Check CloudWatch logs for the orchestrator Lambda to see what the agent is actually doing:"
echo "   aws logs tail /aws/lambda/<orchestrator-function-name> --follow"
echo ""

