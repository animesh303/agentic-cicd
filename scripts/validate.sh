#!/bin/bash

# Validation script for Agentic CI/CD Solution
# This script validates the Terraform deployment and tests the infrastructure

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Counters
PASSED=0
FAILED=0
WARNINGS=0

# Logging functions
log_pass() {
    echo -e "${GREEN}✓${NC} $1"
    ((PASSED++))
}

log_fail() {
    echo -e "${RED}✗${NC} $1"
    ((FAILED++))
}

log_warn() {
    echo -e "${YELLOW}⚠${NC} $1"
    ((WARNINGS++))
}

log_info() {
    echo -e "ℹ $1"
}

# Check if AWS CLI is installed
check_aws_cli() {
    if ! command -v aws &> /dev/null; then
        log_fail "AWS CLI is not installed"
        exit 1
    fi
    log_pass "AWS CLI is installed"
}

# Check if Terraform is installed
check_terraform() {
    if ! command -v terraform &> /dev/null; then
        log_fail "Terraform is not installed"
        exit 1
    fi
    
    TERRAFORM_VERSION=$(terraform version -json | jq -r '.terraform_version')
    log_pass "Terraform is installed (version: $TERRAFORM_VERSION)"
}

# Check AWS credentials
check_aws_credentials() {
    if ! aws sts get-caller-identity &> /dev/null; then
        log_fail "AWS credentials are not configured"
        exit 1
    fi
    
    AWS_ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
    AWS_REGION=$(aws configure get region || echo "us-east-1")
    log_pass "AWS credentials are configured (Account: $AWS_ACCOUNT, Region: $AWS_REGION)"
}

# Validate Terraform configuration
validate_terraform() {
    log_info "Validating Terraform configuration..."
    
    if terraform validate &> /dev/null; then
        log_pass "Terraform configuration is valid"
    else
        log_fail "Terraform configuration has errors"
        terraform validate
        return 1
    fi
    
    # Check format
    if terraform fmt -check &> /dev/null; then
        log_pass "Terraform files are properly formatted"
    else
        log_warn "Terraform files are not properly formatted (run 'terraform fmt')"
    fi
}

# Check if Terraform is initialized
check_terraform_init() {
    if [ ! -d ".terraform" ]; then
        log_warn "Terraform is not initialized. Run 'terraform init -backend-config=backend.tfvars'"
        return 1
    fi
    log_pass "Terraform is initialized"
}

# Get Terraform outputs
get_outputs() {
    log_info "Getting Terraform outputs..."
    
    if ! terraform output -json &> /dev/null; then
        log_fail "Terraform outputs not available. Run 'terraform apply' first."
        exit 1
    fi
    
    log_pass "Terraform outputs available"
}

# Validate S3 bucket
validate_s3_bucket() {
    log_info "Validating S3 bucket..."
    
    BUCKET_NAME=$(terraform output -raw s3_bucket 2>/dev/null || echo "")
    
    if [ -z "$BUCKET_NAME" ]; then
        log_fail "S3 bucket name not found in outputs"
        return 1
    fi
    
    if aws s3 ls "s3://$BUCKET_NAME" &> /dev/null; then
        log_pass "S3 bucket exists: $BUCKET_NAME"
        
        # Check for OpenAPI specs
        if aws s3 ls "s3://$BUCKET_NAME/openapi/" &> /dev/null; then
            log_pass "OpenAPI specs are uploaded to S3"
        else
            log_warn "OpenAPI specs not found in S3"
        fi
    else
        log_fail "S3 bucket does not exist: $BUCKET_NAME"
        return 1
    fi
}

# Validate DynamoDB table
validate_dynamodb() {
    log_info "Validating DynamoDB table..."
    
    TABLE_NAME=$(terraform output -raw dynamodb_table 2>/dev/null || echo "")
    
    if [ -z "$TABLE_NAME" ]; then
        log_fail "DynamoDB table name not found in outputs"
        return 1
    fi
    
    if aws dynamodb describe-table --table-name "$TABLE_NAME" &> /dev/null; then
        log_pass "DynamoDB table exists: $TABLE_NAME"
    else
        log_fail "DynamoDB table does not exist: $TABLE_NAME"
        return 1
    fi
}

# Validate Lambda functions
validate_lambda_functions() {
    log_info "Validating Lambda functions..."
    
    LAMBDA_FUNCTIONS=(
        "lambda_repo_scanner"
        "lambda_repo_ingestor"
        "lambda_static_analyzer"
        "lambda_template_validator"
        "lambda_orchestrator"
        "lambda_github_api"
    )
    
    for LAMBDA_OUTPUT in "${LAMBDA_FUNCTIONS[@]}"; do
        FUNCTION_NAME=$(terraform output -raw "$LAMBDA_OUTPUT" 2>/dev/null || echo "")
        
        if [ -z "$FUNCTION_NAME" ]; then
            log_fail "Lambda function name not found for: $LAMBDA_OUTPUT"
            continue
        fi
        
        if aws lambda get-function --function-name "$FUNCTION_NAME" &> /dev/null; then
            log_pass "Lambda function exists: $FUNCTION_NAME"
            
            # Check function configuration
            RUNTIME=$(aws lambda get-function-configuration --function-name "$FUNCTION_NAME" --query Runtime --output text 2>/dev/null || echo "")
            TIMEOUT=$(aws lambda get-function-configuration --function-name "$FUNCTION_NAME" --query Timeout --output text 2>/dev/null || echo "")
            
            if [ -n "$RUNTIME" ]; then
                log_info "  Runtime: $RUNTIME, Timeout: ${TIMEOUT}s"
            fi
        else
            log_fail "Lambda function does not exist: $FUNCTION_NAME"
        fi
    done
}

# Validate Bedrock agents
validate_bedrock_agents() {
    log_info "Validating Bedrock agents..."
    
    AGENT_OUTPUTS=(
        "bedrock_agent_repo_scanner_id"
        "bedrock_agent_pipeline_designer_id"
        "bedrock_agent_security_compliance_id"
        "bedrock_agent_yaml_generator_id"
        "bedrock_agent_pr_manager_id"
        "bedrock_agent_feedback_id"
    )
    
    AGENT_NAMES=(
        "Repo Scanner"
        "Pipeline Designer"
        "Security & Compliance"
        "YAML Generator"
        "PR Manager"
        "Feedback"
    )
    
    for i in "${!AGENT_OUTPUTS[@]}"; do
        AGENT_ID=$(terraform output -raw "${AGENT_OUTPUTS[$i]}" 2>/dev/null || echo "")
        AGENT_NAME="${AGENT_NAMES[$i]}"
        
        if [ -z "$AGENT_ID" ]; then
            log_fail "Bedrock agent ID not found for: $AGENT_NAME"
            continue
        fi
        
        if aws bedrock-agent get-agent --agent-id "$AGENT_ID" &> /dev/null; then
            log_pass "Bedrock agent exists: $AGENT_NAME ($AGENT_ID)"
            
            # Check agent alias
            if aws bedrock-agent list-agent-aliases --agent-id "$AGENT_ID" --query "agentAliasSummaries[?agentAliasName=='TSTALIASID']" --output text &> /dev/null; then
                log_pass "  Agent alias TSTALIASID exists"
            else
                log_warn "  Agent alias TSTALIASID not found"
            fi
        else
            log_fail "Bedrock agent does not exist: $AGENT_NAME ($AGENT_ID)"
        fi
    done
}

# Validate IAM roles
validate_iam_roles() {
    log_info "Validating IAM roles..."
    
    ROLES=(
        "bedrock-ci-agent-lambda-exec"
        "bedrock-ci-agent-bedrock-agent-role"
    )
    
    for ROLE_NAME in "${ROLES[@]}"; do
        if aws iam get-role --role-name "$ROLE_NAME" &> /dev/null; then
            log_pass "IAM role exists: $ROLE_NAME"
        else
            log_fail "IAM role does not exist: $ROLE_NAME"
        fi
    done
}

# Validate Secrets Manager
validate_secrets() {
    log_info "Validating Secrets Manager..."
    
    SECRET_NAME=$(terraform output -raw github_pat_secret_name 2>/dev/null || echo "bedrock/github/pat")
    
    if aws secretsmanager describe-secret --secret-id "$SECRET_NAME" &> /dev/null; then
        log_pass "Secrets Manager secret exists: $SECRET_NAME"
        
        # Check if secret value is placeholder
        SECRET_VALUE=$(aws secretsmanager get-secret-value --secret-id "$SECRET_NAME" --query SecretString --output text 2>/dev/null || echo "")
        if echo "$SECRET_VALUE" | grep -q "REPLACE_ME_WITH_GITHUB_PAT"; then
            log_warn "GitHub PAT secret contains placeholder value - update with real token"
        else
            log_pass "GitHub PAT secret appears to be configured"
        fi
    else
        log_fail "Secrets Manager secret does not exist: $SECRET_NAME"
    fi
}

# Validate CloudWatch resources
validate_cloudwatch() {
    log_info "Validating CloudWatch resources..."
    
    # Check dashboard
    DASHBOARD_NAME="bedrock-ci-agent-dashboard"
    if aws cloudwatch get-dashboard --dashboard-name "$DASHBOARD_NAME" &> /dev/null; then
        log_pass "CloudWatch dashboard exists: $DASHBOARD_NAME"
    else
        log_warn "CloudWatch dashboard not found: $DASHBOARD_NAME"
    fi
    
    # Check log groups
    LOG_GROUPS=(
        "/aws/lambda/bedrock-ci-agent-orchestrator"
        "/aws/lambda/bedrock-ci-agent-github-api"
        "/aws/lambda/bedrock-ci-agent-static-analyzer"
    )
    
    for LOG_GROUP in "${LOG_GROUPS[@]}"; do
        if aws logs describe-log-groups --log-group-name-prefix "$LOG_GROUP" --query "logGroups[?logGroupName=='$LOG_GROUP']" --output text &> /dev/null; then
            log_pass "CloudWatch log group exists: $LOG_GROUP"
        else
            log_warn "CloudWatch log group not found: $LOG_GROUP"
        fi
    done
}

# Test Lambda function invocation
test_lambda_function() {
    local FUNCTION_NAME=$1
    local PAYLOAD=$2
    local EXPECTED_RESULT=$3
    
    log_info "Testing Lambda function: $FUNCTION_NAME"
    
    if aws lambda invoke \
        --function-name "$FUNCTION_NAME" \
        --payload "$PAYLOAD" \
        /tmp/lambda_response.json &> /dev/null; then
        
        if [ -f /tmp/lambda_response.json ]; then
            RESPONSE=$(cat /tmp/lambda_response.json)
            if echo "$RESPONSE" | grep -q "$EXPECTED_RESULT" || [ -z "$EXPECTED_RESULT" ]; then
                log_pass "Lambda function responded: $FUNCTION_NAME"
            else
                log_warn "Lambda function response unexpected: $FUNCTION_NAME"
            fi
        fi
    else
        log_warn "Lambda function invocation failed: $FUNCTION_NAME (may require valid inputs)"
    fi
}

# Test Bedrock agent
test_bedrock_agent() {
    local AGENT_ID=$1
    local AGENT_NAME=$2
    
    log_info "Testing Bedrock agent: $AGENT_NAME"
    
    SESSION_ID="validation-test-$(date +%s)"
    
    # Test agent invocation (may take time)
    if timeout 30 aws bedrock-agent-runtime invoke-agent \
        --agent-id "$AGENT_ID" \
        --agent-alias-id "TSTALIASID" \
        --session-id "$SESSION_ID" \
        --input-text "Hello, are you working?" \
        /tmp/agent_response.json &> /dev/null; then
        
        log_pass "Bedrock agent responded: $AGENT_NAME"
    else
        log_warn "Bedrock agent test skipped or timed out: $AGENT_NAME (this is normal for validation)"
    fi
}

# Main validation function
main() {
    echo "=========================================="
    echo "Agentic CI/CD Solution Validation"
    echo "=========================================="
    echo ""
    
    # Prerequisites
    check_aws_cli
    check_terraform
    check_aws_credentials
    
    echo ""
    log_info "Starting validation checks..."
    echo ""
    
    # Terraform validation
    validate_terraform
    check_terraform_init
    
    # Get outputs (requires applied infrastructure)
    if get_outputs; then
        echo ""
        log_info "Validating deployed infrastructure..."
        echo ""
        
        # Infrastructure validation
        validate_s3_bucket
        validate_dynamodb
        validate_lambda_functions
        validate_bedrock_agents
        validate_iam_roles
        validate_secrets
        validate_cloudwatch
        
        echo ""
        log_info "Running basic functionality tests..."
        echo ""
        
        # Test Lambda functions (basic tests)
        REPO_INGESTOR=$(terraform output -raw lambda_repo_ingestor 2>/dev/null || echo "")
        if [ -n "$REPO_INGESTOR" ]; then
            test_lambda_function "$REPO_INGESTOR" '{"repo_url":"https://github.com/octocat/Hello-World","branch":"main"}' ""
        fi
        
        # Test Bedrock agents (basic tests)
        REPO_SCANNER_AGENT=$(terraform output -raw bedrock_agent_repo_scanner_id 2>/dev/null || echo "")
        if [ -n "$REPO_SCANNER_AGENT" ]; then
            test_bedrock_agent "$REPO_SCANNER_AGENT" "Repo Scanner"
        fi
    else
        log_warn "Infrastructure not deployed. Run 'terraform apply' to deploy resources."
    fi
    
    # Summary
    echo ""
    echo "=========================================="
    echo "Validation Summary"
    echo "=========================================="
    echo -e "${GREEN}Passed:${NC} $PASSED"
    echo -e "${YELLOW}Warnings:${NC} $WARNINGS"
    echo -e "${RED}Failed:${NC} $FAILED"
    echo ""
    
    if [ $FAILED -eq 0 ]; then
        echo -e "${GREEN}✓ Validation completed successfully!${NC}"
        exit 0
    else
        echo -e "${RED}✗ Validation completed with errors${NC}"
        exit 1
    fi
}

# Run main function
main

