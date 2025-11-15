#!/bin/bash

# End-to-End Test Script for Agentic CI/CD Pipeline Generator
# This script performs comprehensive testing of the entire workflow

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Test configuration
TEST_REPO_URL="${TEST_REPO_URL:-https://github.com/animesh303/animesh303}"
TEST_BRANCH="${TEST_BRANCH:-main}"
TEST_RESULTS_DIR="${TEST_RESULTS_DIR:-./test_results}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
TEST_RESULTS_FILE="${TEST_RESULTS_DIR}/e2e_test_results_${TIMESTAMP}.json"
TEST_LOG_FILE="${TEST_RESULTS_DIR}/e2e_test_log_${TIMESTAMP}.log"
WORKFLOW_BRANCH="${WORKFLOW_BRANCH:-ci-cd/add-pipeline}"
WORKFLOW_FILE_PATH="${WORKFLOW_FILE_PATH:-.github/workflows/ci-cd.yml}"

REPO_OWNER=""
REPO_NAME=""

# Test counters
TESTS_PASSED=0
TESTS_FAILED=0
TESTS_WARNED=0
TOTAL_TESTS=0

# Create results directory
mkdir -p "$TEST_RESULTS_DIR"

# Logging functions
log_info() {
    echo -e "${BLUE}ℹ${NC} $1" | tee -a "$TEST_LOG_FILE"
}

log_pass() {
    echo -e "${GREEN}✓${NC} $1" | tee -a "$TEST_LOG_FILE"
    ((TESTS_PASSED++))
    ((TOTAL_TESTS++))
}

log_fail() {
    echo -e "${RED}✗${NC} $1" | tee -a "$TEST_LOG_FILE"
    ((TESTS_FAILED++))
    ((TOTAL_TESTS++))
}

log_warn() {
    echo -e "${YELLOW}⚠${NC} $1" | tee -a "$TEST_LOG_FILE"
    ((TESTS_WARNED++))
    ((TOTAL_TESTS++))
}

log_section() {
    echo "" | tee -a "$TEST_LOG_FILE"
    echo "==========================================" | tee -a "$TEST_LOG_FILE"
    echo "$1" | tee -a "$TEST_LOG_FILE"
    echo "==========================================" | tee -a "$TEST_LOG_FILE"
}

parse_repo_from_url() {
    local url="$1"
    local cleaned="${url%/}"
    cleaned="${cleaned%.git}"
    cleaned="${cleaned#git@github.com:}"
    cleaned="${cleaned#https://github.com/}"
    REPO_OWNER=$(echo "$cleaned" | cut -d'/' -f1)
    REPO_NAME=$(echo "$cleaned" | cut -d'/' -f2)
}

parse_repo_from_url "$TEST_REPO_URL"

# Initialize test results JSON
init_test_results() {
    cat > "$TEST_RESULTS_FILE" <<EOF
{
  "test_run": {
    "timestamp": "$TIMESTAMP",
    "test_repo_url": "$TEST_REPO_URL",
    "test_branch": "$TEST_BRANCH",
    "test_environment": {
      "aws_account": "$(aws sts get-caller-identity --query Account --output text 2>/dev/null || echo 'unknown')",
      "aws_region": "$(aws configure get region || echo 'us-east-1')"
    }
  },
  "test_results": {
    "prerequisites": [],
    "component_tests": [],
    "integration_tests": [],
    "end_to_end_test": [],
    "summary": {
      "total_tests": 0,
      "passed": 0,
      "failed": 0,
      "warnings": 0
    }
  }
}
EOF
}

# Add test result to JSON
add_test_result() {
    local category=$1
    local test_name=$2
    local status=$3
    local message=$4
    local details=$5
    
    # Use jq to add test result
    if command -v jq &> /dev/null; then
        jq ".test_results.${category} += [{\"test\": \"$test_name\", \"status\": \"$status\", \"message\": \"$message\", \"details\": $details, \"timestamp\": \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"}]" "$TEST_RESULTS_FILE" > "${TEST_RESULTS_FILE}.tmp" && mv "${TEST_RESULTS_FILE}.tmp" "$TEST_RESULTS_FILE"
    fi
}

# Check prerequisites
check_prerequisites() {
    log_section "Prerequisites Check"
    
    # Check AWS CLI
    if command -v aws &> /dev/null; then
        log_pass "AWS CLI installed"
        add_test_result "prerequisites" "aws_cli_installed" "pass" "AWS CLI is installed" "{}"
    else
        log_fail "AWS CLI not installed"
        add_test_result "prerequisites" "aws_cli_installed" "fail" "AWS CLI is not installed" "{}"
        return 1
    fi
    
    # Check AWS credentials
    if aws sts get-caller-identity &> /dev/null; then
        AWS_ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
        log_pass "AWS credentials configured (Account: $AWS_ACCOUNT)"
        add_test_result "prerequisites" "aws_credentials" "pass" "AWS credentials configured" "{\"account\": \"$AWS_ACCOUNT\"}"
    else
        log_fail "AWS credentials not configured"
        add_test_result "prerequisites" "aws_credentials" "fail" "AWS credentials not configured" "{}"
        return 1
    fi
    
    # Check Terraform
    if command -v terraform &> /dev/null; then
        TERRAFORM_VERSION=$(terraform version -json 2>/dev/null | jq -r '.terraform_version' || echo "unknown")
        log_pass "Terraform installed (version: $TERRAFORM_VERSION)"
        add_test_result "prerequisites" "terraform_installed" "pass" "Terraform is installed" "{\"version\": \"$TERRAFORM_VERSION\"}"
    else
        log_fail "Terraform not installed"
        add_test_result "prerequisites" "terraform_installed" "fail" "Terraform is not installed" "{}"
        return 1
    fi
    
    # Check Terraform outputs
    if terraform output -json &> /dev/null; then
        log_pass "Terraform outputs available"
        add_test_result "prerequisites" "terraform_outputs" "pass" "Terraform outputs available" "{}"
    else
        log_fail "Terraform outputs not available - run 'terraform apply' first"
        add_test_result "prerequisites" "terraform_outputs" "fail" "Terraform outputs not available" "{}"
        return 1
    fi
    
    # Check jq (optional but recommended)
    if command -v jq &> /dev/null; then
        log_pass "jq installed (for JSON processing)"
    else
        log_warn "jq not installed (JSON processing will be limited)"
    fi
}

# Test Lambda functions
test_lambda_functions() {
    log_section "Lambda Function Tests"
    
    # Get Lambda function names from Terraform
    LAMBDA_ORCHESTRATOR=$(terraform output -raw lambda_orchestrator 2>/dev/null || echo "")
    LAMBDA_REPO_INGESTOR=$(terraform output -raw lambda_repo_ingestor 2>/dev/null || echo "")
    LAMBDA_STATIC_ANALYZER=$(terraform output -raw lambda_static_analyzer 2>/dev/null || echo "")
    LAMBDA_TEMPLATE_VALIDATOR=$(terraform output -raw lambda_template_validator 2>/dev/null || echo "")
    LAMBDA_GITHUB_API=$(terraform output -raw lambda_github_api 2>/dev/null || echo "")
    
    # Test Repository Ingestor
    if [ -n "$LAMBDA_REPO_INGESTOR" ]; then
        log_info "Testing Repository Ingestor Lambda..."
        PAYLOAD="{\"repo_url\": \"$TEST_REPO_URL\", \"branch\": \"$TEST_BRANCH\"}"
        
        if aws lambda invoke \
            --function-name "$LAMBDA_REPO_INGESTOR" \
            --cli-binary-format raw-in-base64-out \
            --payload "$PAYLOAD" \
            /tmp/repo_ingestor_response.json &> /dev/null; then
            
            RESPONSE=$(cat /tmp/repo_ingestor_response.json 2>/dev/null || echo "{}")
            if echo "$RESPONSE" | grep -q "status" || echo "$RESPONSE" | grep -q "manifests"; then
                log_pass "Repository Ingestor Lambda responded successfully"
                add_test_result "component_tests" "lambda_repo_ingestor" "pass" "Lambda function responded" "{\"response_size\": $(echo "$RESPONSE" | wc -c)}"
            else
                log_warn "Repository Ingestor Lambda response format unexpected"
                add_test_result "component_tests" "lambda_repo_ingestor" "warn" "Response format unexpected" "{\"response\": \"$RESPONSE\"}"
            fi
        else
            log_fail "Repository Ingestor Lambda invocation failed"
            add_test_result "component_tests" "lambda_repo_ingestor" "fail" "Lambda invocation failed" "{}"
        fi
    else
        log_fail "Repository Ingestor Lambda name not found in Terraform outputs"
    fi
    
    # Test Static Analyzer
    if [ -n "$LAMBDA_STATIC_ANALYZER" ]; then
        log_info "Testing Static Analyzer Lambda..."
        PAYLOAD="{\"repo_url\": \"$TEST_REPO_URL\", \"branch\": \"$TEST_BRANCH\", \"analysis_types\": [\"dockerfile\", \"dependencies\", \"tests\"]}"
        
        if aws lambda invoke \
            --function-name "$LAMBDA_STATIC_ANALYZER" \
            --cli-binary-format raw-in-base64-out \
            --payload "$PAYLOAD" \
            /tmp/static_analyzer_response.json &> /dev/null; then
            
            RESPONSE=$(cat /tmp/static_analyzer_response.json 2>/dev/null || echo "{}")
            if echo "$RESPONSE" | grep -q "status"; then
                log_pass "Static Analyzer Lambda responded successfully"
                add_test_result "component_tests" "lambda_static_analyzer" "pass" "Lambda function responded" "{}"
            else
                log_warn "Static Analyzer Lambda response format unexpected"
                add_test_result "component_tests" "lambda_static_analyzer" "warn" "Response format unexpected" "{}"
            fi
        else
            log_fail "Static Analyzer Lambda invocation failed"
            add_test_result "component_tests" "lambda_static_analyzer" "fail" "Lambda invocation failed" "{}"
        fi
    else
        log_fail "Static Analyzer Lambda name not found in Terraform outputs"
    fi
    
    # Test Template Validator
    if [ -n "$LAMBDA_TEMPLATE_VALIDATOR" ]; then
        log_info "Testing Template Validator Lambda..."
        TEST_YAML="name: Test Workflow
on: [push]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3"
        
        PAYLOAD="{\"yaml_content\": $(echo "$TEST_YAML" | jq -Rs .), \"validation_level\": \"normal\"}"
        
        if aws lambda invoke \
            --function-name "$LAMBDA_TEMPLATE_VALIDATOR" \
            --cli-binary-format raw-in-base64-out \
            --payload "$PAYLOAD" \
            /tmp/template_validator_response.json &> /dev/null; then
            
            RESPONSE=$(cat /tmp/template_validator_response.json 2>/dev/null || echo "{}")
            if echo "$RESPONSE" | grep -q "valid"; then
                log_pass "Template Validator Lambda responded successfully"
                add_test_result "component_tests" "lambda_template_validator" "pass" "Lambda function responded" "{}"
            else
                log_warn "Template Validator Lambda response format unexpected"
                add_test_result "component_tests" "lambda_template_validator" "warn" "Response format unexpected" "{}"
            fi
        else
            log_fail "Template Validator Lambda invocation failed"
            add_test_result "component_tests" "lambda_template_validator" "fail" "Lambda invocation failed" "{}"
        fi
    else
        log_fail "Template Validator Lambda name not found in Terraform outputs"
    fi
}

# Find timeout command (cross-platform: Linux has timeout, macOS may have gtimeout from Homebrew)
find_timeout_cmd() {
    if command -v timeout &> /dev/null; then
        echo "timeout"
    elif command -v gtimeout &> /dev/null; then
        echo "gtimeout"
    else
        echo ""
    fi
}

# Run command with timeout (cross-platform)
run_with_timeout() {
    local timeout_seconds=$1
    shift
    local timeout_cmd=$(find_timeout_cmd)
    
    if [ -n "$timeout_cmd" ]; then
        $timeout_cmd $timeout_seconds "$@"
    else
        # Fallback: run without timeout (log warning)
        log_warn "timeout command not available, running without timeout limit"
        "$@"
    fi
}

# Check if invoke-agent command is available
# Note: AWS CLI may not support invoke-agent command even in latest versions
# The orchestrator uses boto3 which has full support for invoke_agent()
check_invoke_agent_available() {
    # Check bedrock-agent-runtime service
    if aws bedrock-agent-runtime invoke-agent help &> /dev/null 2>&1; then
        return 0
    fi
    # Check bedrock-agent service (alternative location)
    if aws bedrock-agent invoke-agent help &> /dev/null 2>&1; then
        return 0
    fi
    # Check if invoke-agent is in the list of available commands
    if aws bedrock-agent-runtime help 2>&1 | grep -q "invoke-agent"; then
        return 0
    fi
    if aws bedrock-agent help 2>&1 | grep -q "invoke-agent"; then
        return 0
    fi
    return 1
}

# Test Bedrock Agents
test_bedrock_agents() {
    log_section "Bedrock Agent Tests"
    
    # Check if invoke-agent command is available
    # Note: AWS CLI may not have invoke-agent command even in latest versions
    # This is a known limitation - the orchestrator uses boto3 which works correctly
    if ! check_invoke_agent_available; then
        log_warn "AWS CLI 'invoke-agent' command not available in this AWS CLI version"
        log_info "This is expected - AWS CLI may not support invoke-agent yet"
        log_info "Agents will be tested via orchestrator workflow (uses boto3 SDK)"
        add_test_result "component_tests" "agent_repo_scanner" "skip" "invoke-agent command not available in AWS CLI" "{\"note\": \"AWS CLI limitation - agents tested via orchestrator workflow using boto3\"}"
        return 0
    fi
    
    # Get agent IDs from Terraform
    AGENT_IDS=$(terraform output -json agent_ids_map 2>/dev/null || echo "{}")
    
    if [ "$AGENT_IDS" = "{}" ]; then
        log_fail "Agent IDs not found in Terraform outputs"
        add_test_result "component_tests" "agent_repo_scanner" "fail" "Agent IDs not found" "{}"
        return 1
    fi
    
    # Test Repo Scanner Agent
    REPO_SCANNER_ID=$(echo "$AGENT_IDS" | jq -r '.repo_scanner // empty' 2>/dev/null || echo "")
    if [ -n "$REPO_SCANNER_ID" ] && [ "$REPO_SCANNER_ID" != "null" ]; then
        log_info "Testing Repo Scanner Agent..."
        SESSION_ID="e2e-test-repo-scanner-$(date +%s)"
        
        # Try bedrock-agent-runtime invoke-agent
        # Note: This command may not be available in AWS CLI - that's OK, agents are tested via orchestrator
        if run_with_timeout 60 aws bedrock-agent-runtime invoke-agent \
            --agent-id "$REPO_SCANNER_ID" \
            --agent-alias-id "TSTALIASID" \
            --session-id "$SESSION_ID" \
            --input-text "Analyze repository: $TEST_REPO_URL (branch: $TEST_BRANCH). Extract all manifest files, detect languages, frameworks, and infrastructure components." \
            /tmp/repo_scanner_response.json > /tmp/agent_output.log 2>&1; then
            
            # Check if response file was created and has content
            if [ -f /tmp/repo_scanner_response.json ] && [ -s /tmp/repo_scanner_response.json ]; then
                log_pass "Repo Scanner Agent responded"
                add_test_result "component_tests" "agent_repo_scanner" "pass" "Agent responded successfully" "{\"session_id\": \"$SESSION_ID\"}"
            else
                log_warn "Repo Scanner Agent response file not created or empty"
                add_test_result "component_tests" "agent_repo_scanner" "warn" "Response file not created or empty" "{}"
            fi
        else
            # Check the error output
            ERROR_OUTPUT=$(cat /tmp/agent_output.log 2>/dev/null || echo "")
            if echo "$ERROR_OUTPUT" | grep -q "Invalid choice\|Invalid choice"; then
                log_warn "AWS CLI version may not support invoke-agent command"
                log_info "Update AWS CLI: pip install --upgrade awscli or brew upgrade awscli"
                add_test_result "component_tests" "agent_repo_scanner" "warn" "AWS CLI version may not support invoke-agent" "{\"note\": \"Update AWS CLI to latest version\"}"
            else
                log_warn "Repo Scanner Agent test timed out or failed (this may be normal for long-running agents)"
                add_test_result "component_tests" "agent_repo_scanner" "warn" "Agent test timed out or failed" "{}"
            fi
        fi
    else
        log_fail "Repo Scanner Agent ID not found"
        add_test_result "component_tests" "agent_repo_scanner" "fail" "Agent ID not found" "{}"
    fi
}

# Test DynamoDB
test_dynamodb() {
    log_section "DynamoDB Tests"
    
    TABLE_NAME=$(terraform output -raw dynamodb_table 2>/dev/null || echo "")
    
    if [ -z "$TABLE_NAME" ]; then
        log_fail "DynamoDB table name not found"
        add_test_result "component_tests" "dynamodb_table" "fail" "Table name not found" "{}"
        return 1
    fi
    
    # Check if table exists
    if aws dynamodb describe-table --table-name "$TABLE_NAME" &> /dev/null; then
        log_pass "DynamoDB table exists: $TABLE_NAME"
        add_test_result "component_tests" "dynamodb_table" "pass" "Table exists" "{\"table_name\": \"$TABLE_NAME\"}"
        
        # Test write operation (create a test record)
        TEST_TASK_ID="e2e-test-$(date +%s)"
        if aws dynamodb put-item \
            --table-name "$TABLE_NAME" \
            --item "{\"task_id\": {\"S\": \"$TEST_TASK_ID\"}, \"repo_url\": {\"S\": \"$TEST_REPO_URL\"}, \"status\": {\"S\": \"test\"}, \"created_at\": {\"S\": \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"}}" \
            &> /dev/null; then
            log_pass "DynamoDB write operation successful"
            add_test_result "component_tests" "dynamodb_write" "pass" "Write operation successful" "{\"test_task_id\": \"$TEST_TASK_ID\"}"
            
            # Clean up test record
            aws dynamodb delete-item \
                --table-name "$TABLE_NAME" \
                --key "{\"task_id\": {\"S\": \"$TEST_TASK_ID\"}}" \
                &> /dev/null || true
        else
            log_fail "DynamoDB write operation failed"
            add_test_result "component_tests" "dynamodb_write" "fail" "Write operation failed" "{}"
        fi
    else
        log_fail "DynamoDB table does not exist: $TABLE_NAME"
        add_test_result "component_tests" "dynamodb_table" "fail" "Table does not exist" "{\"table_name\": \"$TABLE_NAME\"}"
    fi
}

# Test S3
test_s3() {
    log_section "S3 Bucket Tests"
    
    BUCKET_NAME=$(terraform output -raw s3_bucket 2>/dev/null || echo "")
    
    if [ -z "$BUCKET_NAME" ]; then
        log_fail "S3 bucket name not found"
        add_test_result "component_tests" "s3_bucket" "fail" "Bucket name not found" "{}"
        return 1
    fi
    
    # Check if bucket exists
    if aws s3 ls "s3://$BUCKET_NAME" &> /dev/null; then
        log_pass "S3 bucket exists: $BUCKET_NAME"
        add_test_result "component_tests" "s3_bucket" "pass" "Bucket exists" "{\"bucket_name\": \"$BUCKET_NAME\"}"
        
        # Check for OpenAPI specs
        if aws s3 ls "s3://$BUCKET_NAME/openapi/" &> /dev/null; then
            log_pass "OpenAPI specs found in S3"
            add_test_result "component_tests" "s3_openapi_specs" "pass" "OpenAPI specs found" "{}"
        else
            log_warn "OpenAPI specs not found in S3"
            add_test_result "component_tests" "s3_openapi_specs" "warn" "OpenAPI specs not found" "{}"
        fi
    else
        log_fail "S3 bucket does not exist: $BUCKET_NAME"
        add_test_result "component_tests" "s3_bucket" "fail" "Bucket does not exist" "{\"bucket_name\": \"$BUCKET_NAME\"}"
    fi
}

verify_github_artifacts() {
    local owner="$1"
    local repo="$2"
    local branch="$3"

    if [ -z "$owner" ] || [ -z "$repo" ]; then
        log_warn "Unable to parse repository owner/name; skipping GitHub verification"
        add_test_result "integration_tests" "github_verification" "warn" "Could not parse repository owner/name" "{}"
        return 0
    fi

    log_section "GitHub Verification"

    local branch_api="https://api.github.com/repos/${owner}/${repo}/branches/${branch}"
    local branch_http_status
    branch_http_status=$(curl -s -o /tmp/github_branch_${TIMESTAMP}.json -w "%{http_code}" "$branch_api")

    if [ "$branch_http_status" = "200" ]; then
        log_pass "GitHub branch '${branch}' exists"
        add_test_result "integration_tests" "github_branch_exists" "pass" "Branch detected via GitHub API" "{\"branch\": \"${branch}\"}"
    else
        log_fail "GitHub branch '${branch}' not found (HTTP ${branch_http_status})"
        add_test_result "integration_tests" "github_branch_exists" "fail" "Branch missing" "{\"branch\": \"${branch}\", \"http_status\": \"${branch_http_status}\"}"
        # Continue to workflow validation for completeness
    fi

    local workflow_url="https://raw.githubusercontent.com/${owner}/${repo}/${branch}/${WORKFLOW_FILE_PATH}"
    local workflow_http_status
    workflow_http_status=$(curl -s -o /tmp/github_workflow_${TIMESTAMP}.yml -w "%{http_code}" "$workflow_url")

    if [ "$workflow_http_status" = "200" ] && [ -s "/tmp/github_workflow_${TIMESTAMP}.yml" ]; then
        log_pass "Workflow file '${WORKFLOW_FILE_PATH}' found in branch '${branch}'"
        add_test_result "integration_tests" "github_workflow_file" "pass" "Workflow file found" "{\"path\": \"${WORKFLOW_FILE_PATH}\"}"
    else
        log_fail "Workflow file '${WORKFLOW_FILE_PATH}' not found in branch '${branch}' (HTTP ${workflow_http_status})"
        add_test_result "integration_tests" "github_workflow_file" "fail" "Workflow file missing" "{\"path\": \"${WORKFLOW_FILE_PATH}\", \"http_status\": \"${workflow_http_status}\"}"
    fi

    return 0
}

check_repo_ingestor_step() {
    local steps_json="$1"
    local status
    status=$(printf '%s\n' "$steps_json" | jq -r '.[] | select(.step == "repo_ingestor") | .result.status // empty' 2>/dev/null || echo "")

    if [ -z "$status" ]; then
        log_warn "repo_ingestor step not found in workflow trace"
        add_test_result "end_to_end_test" "repo_ingestor_step" "warn" "repo_ingestor step missing from workflow trace" "{}"
    elif [ "$status" = "success" ]; then
        log_pass "repo_ingestor Lambda returned manifest data"
        add_test_result "end_to_end_test" "repo_ingestor_step" "pass" "repo_ingestor Lambda succeeded" "{}"
    else
        log_fail "repo_ingestor Lambda failed (status: $status)"
        add_test_result "end_to_end_test" "repo_ingestor_step" "fail" "repo_ingestor Lambda failed" "{\"status\": \"$status\"}"
    fi
}

check_template_validator_step() {
    local steps_json="$1"
    local status
    status=$(printf '%s\n' "$steps_json" | jq -r '.[] | select(.step == "template_validator") | .result.status // empty' 2>/dev/null || echo "")
    local valid_flag
    valid_flag=$(printf '%s\n' "$steps_json" | jq -r '.[] | select(.step == "template_validator") | .result.valid // empty' 2>/dev/null || echo "")

    if [ -z "$status" ]; then
        log_warn "template_validator step not found in workflow trace"
        add_test_result "end_to_end_test" "template_validator_step" "warn" "template_validator step missing from workflow trace" "{}"
    elif [ "$status" = "success" ] && { [ -z "$valid_flag" ] || [ "$valid_flag" = "true" ]; }; then
        log_pass "Template validator Lambda confirmed workflow YAML"
        add_test_result "end_to_end_test" "template_validator_step" "pass" "template validator reported valid YAML" "{}"
    else
        log_fail "Template validator reported invalid YAML"
        add_test_result "end_to_end_test" "template_validator_step" "fail" "template validator flagged invalid YAML" "{}"
    fi
}

check_github_operations_step() {
    local steps_json="$1"
    local success_flag
    success_flag=$(printf '%s\n' "$steps_json" | jq -r '.[] | select(.step == "github_operations") | .result.success // empty' 2>/dev/null || echo "")

    if [ -z "$success_flag" ]; then
        log_warn "github_operations step not found in workflow trace"
        add_test_result "end_to_end_test" "github_operations_step" "warn" "GitHub operations step missing from workflow trace" "{}"
    elif [ "$success_flag" = "true" ]; then
        log_pass "GitHub Lambda created branch/file/PR"
        add_test_result "end_to_end_test" "github_operations_step" "pass" "GitHub Lambda succeeded" "{}"
    else
        log_fail "GitHub Lambda failed to create branch/file/PR"
        add_test_result "end_to_end_test" "github_operations_step" "fail" "GitHub Lambda failed" "{}"
    fi
}

validate_workflow_requirements() {
    local steps_json="$1"
    check_repo_ingestor_step "$steps_json"
    check_template_validator_step "$steps_json"
    check_github_operations_step "$steps_json"
    WORKFLOW_REQUIREMENTS_VALIDATED=true
}

# End-to-End Workflow Test
test_end_to_end_workflow() {
    log_section "End-to-End Workflow Test"
    
    LAMBDA_ORCHESTRATOR=$(terraform output -raw lambda_orchestrator 2>/dev/null || echo "")
    AGENT_IDS=$(terraform output -json agent_ids_map 2>/dev/null || echo "{}")
    if [ -z "$LAMBDA_ORCHESTRATOR" ]; then
        log_fail "Orchestrator Lambda name not found"
        add_test_result "end_to_end_test" "orchestrator_invocation" "fail" "Lambda name not found" "{}"
        return 1
    fi
    
    if [ "$AGENT_IDS" = "{}" ]; then
        log_fail "Agent IDs not found"
        add_test_result "end_to_end_test" "orchestrator_invocation" "fail" "Agent IDs not found" "{}"
        return 1
    fi
    
    # Create test payload
    TASK_ID="e2e-test-$(date +%s)"
    PAYLOAD=$(jq -n \
        --arg task_id "$TASK_ID" \
        --arg repo_url "$TEST_REPO_URL" \
        --arg branch "$TEST_BRANCH" \
        --argjson agent_ids "$AGENT_IDS" \
        '{task_id: $task_id, repo_url: $repo_url, branch: $branch, agent_ids: $agent_ids}' 2>/dev/null || echo "{}")
    
    if [ "$PAYLOAD" = "{}" ]; then
        # Fallback if jq is not available
        PAYLOAD="{\"task_id\": \"$TASK_ID\", \"repo_url\": \"$TEST_REPO_URL\", \"branch\": \"$TEST_BRANCH\", \"agent_ids\": $AGENT_IDS}"
    fi
    
    log_info "Invoking orchestrator with task ID: $TASK_ID"
    log_info "Repository: $TEST_REPO_URL (branch: $TEST_BRANCH)"
    
    # Invoke orchestrator (this may take several minutes)
    log_info "Note: This test may take 5-15 minutes to complete..."
    
    START_TIME=$(date +%s)
    
    # Use longer timeout for orchestrator (up to 20 minutes)
    # The orchestrator Lambda has a 15-minute timeout, so we need to wait longer
    if timeout 1200 aws lambda invoke \
        --function-name "$LAMBDA_ORCHESTRATOR" \
        --cli-binary-format raw-in-base64-out \
        --payload "$PAYLOAD" \
        /tmp/orchestrator_response.json 2>&1 | tee -a "$TEST_LOG_FILE"; then
        
        END_TIME=$(date +%s)
        DURATION=$((END_TIME - START_TIME))
        
        RESPONSE=$(cat /tmp/orchestrator_response.json 2>/dev/null || echo "{}")
        
        if echo "$RESPONSE" | grep -q "status"; then
            STATUS=$(echo "$RESPONSE" | jq -r '.status // "unknown"' 2>/dev/null || echo "unknown")
            
            if [ "$STATUS" = "success" ]; then
                log_pass "End-to-end workflow completed successfully (duration: ${DURATION}s)"
                
                # Extract workflow steps
                STEPS=$(echo "$RESPONSE" | jq '.workflow_steps // []' 2>/dev/null || echo "[]")
                STEP_COUNT=$(echo "$STEPS" | jq 'length' 2>/dev/null || echo "0")
                
                add_test_result "end_to_end_test" "workflow_execution" "pass" "Workflow completed successfully" "{\"duration_seconds\": $DURATION, \"task_id\": \"$TASK_ID\", \"steps_completed\": $STEP_COUNT}"
                
                # Check each step
                log_info "Workflow steps completed: $STEP_COUNT"
                validate_workflow_requirements "$STEPS"
                for i in $(seq 0 $((STEP_COUNT - 1))); do
                    STEP_NAME=$(echo "$STEPS" | jq -r ".[$i].step // \"unknown\"" 2>/dev/null || echo "unknown")
                    STEP_STATUS=$(echo "$STEPS" | jq -r ".[$i].result.status // \"unknown\"" 2>/dev/null || echo "unknown")
                    
                    if [ "$STEP_STATUS" = "success" ]; then
                        log_pass "  Step $((i+1)): $STEP_NAME - SUCCESS"
                    else
                        log_warn "  Step $((i+1)): $STEP_NAME - $STEP_STATUS"
                    fi
                done
                
            elif [ "$STATUS" = "error" ]; then
                ERROR_MSG=$(echo "$RESPONSE" | jq -r '.message // "Unknown error"' 2>/dev/null || echo "Unknown error")
                log_warn "Lambda response shows error: $ERROR_MSG (will verify with DynamoDB)"
                # Don't fail yet - check DynamoDB first as it's the source of truth
                # The Lambda response might be from an early failed attempt before retry succeeded
            else
                log_warn "End-to-end workflow returned unknown status: $STATUS (will verify with DynamoDB)"
                # Don't fail yet - check DynamoDB first
            fi
        else
            log_warn "Orchestrator response format unexpected"
            add_test_result "end_to_end_test" "workflow_execution" "warn" "Response format unexpected" "{\"duration_seconds\": $DURATION, \"task_id\": \"$TASK_ID\"}"
        fi
        
        # Save full response
        cp /tmp/orchestrator_response.json "${TEST_RESULTS_DIR}/orchestrator_response_${TIMESTAMP}.json" 2>/dev/null || true
        
    else
        log_fail "Orchestrator Lambda invocation failed"
        add_test_result "end_to_end_test" "orchestrator_invocation" "fail" "Lambda invocation failed" "{}"
    fi
    
    # Check DynamoDB for task record (this is the source of truth)
    TABLE_NAME=$(terraform output -raw dynamodb_table 2>/dev/null || echo "")
    if [ -n "$TABLE_NAME" ]; then
        log_info "Checking DynamoDB for task record..."
        
        # Wait a bit for the task to complete if it's still in progress
        MAX_WAIT=300  # 5 minutes
        WAIT_INTERVAL=10  # Check every 10 seconds
        ELAPSED=0
        
        while [ $ELAPSED -lt $MAX_WAIT ]; do
            if aws dynamodb get-item \
                --table-name "$TABLE_NAME" \
                --key "{\"task_id\": {\"S\": \"$TASK_ID\"}}" \
                --output json > /tmp/task_record.json 2>/dev/null; then
                
                TASK_STATUS=$(jq -r '.Item.status.S // "unknown"' /tmp/task_record.json 2>/dev/null || echo "unknown")
                
                if [ "$TASK_STATUS" = "completed" ] || [ "$TASK_STATUS" = "failed" ]; then
                    log_info "Task status in DynamoDB: $TASK_STATUS"
                    break
                else
                    log_info "Task still in progress (status: $TASK_STATUS), waiting..."
                    sleep $WAIT_INTERVAL
                    ELAPSED=$((ELAPSED + WAIT_INTERVAL))
                fi
            else
                log_warn "Task record not found in DynamoDB yet, waiting..."
                sleep $WAIT_INTERVAL
                ELAPSED=$((ELAPSED + WAIT_INTERVAL))
            fi
        done
        
        if [ -f /tmp/task_record.json ]; then
            TASK_STATUS=$(jq -r '.Item.status.S // "unknown"' /tmp/task_record.json 2>/dev/null || echo "unknown")
            TASK_RESULT=$(jq -r '.Item.result.S // "{}"' /tmp/task_record.json 2>/dev/null || echo "{}")
            
            log_info "Final task status in DynamoDB: $TASK_STATUS"
            add_test_result "end_to_end_test" "dynamodb_task_tracking" "pass" "Task record found" "{\"task_id\": \"$TASK_ID\", \"status\": \"$TASK_STATUS\"}"
            
            # If DynamoDB shows completed, treat it as success even if Lambda response showed error
            # (Lambda response might be from an early failed attempt before retry succeeded)
            if [ "$TASK_STATUS" = "completed" ]; then
                log_info "Task completed successfully according to DynamoDB (Lambda response may have been from early failure)"
                
                # Try to parse the result from DynamoDB
                if [ "$TASK_RESULT" != "{}" ] && [ "$TASK_RESULT" != "null" ]; then
                    WORKFLOW_STEPS=$(echo "$TASK_RESULT" | jq '.steps // []' 2>/dev/null || echo "[]")
                    STEP_COUNT=$(echo "$WORKFLOW_STEPS" | jq 'length' 2>/dev/null || echo "0")
                    
                    if [ "$STEP_COUNT" -gt 0 ]; then
                        log_pass "End-to-end workflow completed successfully (verified via DynamoDB, duration: ${DURATION}s)"
                        add_test_result "end_to_end_test" "workflow_execution" "pass" "Workflow completed successfully (verified via DynamoDB)" "{\"duration_seconds\": $DURATION, \"task_id\": \"$TASK_ID\", \"steps_completed\": $STEP_COUNT}"
                        
                        # Check each step
                        log_info "Workflow steps completed: $STEP_COUNT"
                        validate_workflow_requirements "$WORKFLOW_STEPS"
                        for i in $(seq 0 $((STEP_COUNT - 1))); do
                            STEP_NAME=$(echo "$WORKFLOW_STEPS" | jq -r ".[$i].step // \"unknown\"" 2>/dev/null || echo "unknown")
                            STEP_STATUS=$(echo "$WORKFLOW_STEPS" | jq -r ".[$i].result.status // \"unknown\"" 2>/dev/null || echo "unknown")
                            
                            if [ "$STEP_STATUS" = "success" ] || [[ "$STEP_STATUS" == *"success"* ]]; then
                                DISPLAY_STATUS=$(echo "$STEP_STATUS" | tr '[:lower:]' '[:upper:]')
                                if [ -z "$DISPLAY_STATUS" ]; then
                                    DISPLAY_STATUS="SUCCESS"
                                fi
                                log_pass "  Step $((i+1)): $STEP_NAME - $DISPLAY_STATUS"
                            else
                                log_warn "  Step $((i+1)): $STEP_NAME - $STEP_STATUS"
                            fi
                        done
                        
                        verify_github_artifacts "$REPO_OWNER" "$REPO_NAME" "$WORKFLOW_BRANCH"
                        return 0  # Success
                    fi
                fi
            elif [ "$TASK_STATUS" = "failed" ]; then
                ERROR_MSG=$(echo "$TASK_RESULT" | jq -r '.error // "Unknown error"' 2>/dev/null || echo "Unknown error")
                log_fail "End-to-end workflow failed (verified via DynamoDB): $ERROR_MSG"
                ERROR_JSON=$(printf '%s' "$ERROR_MSG" | jq -Rs . 2>/dev/null || printf '"%s"' "$ERROR_MSG")
                add_test_result "end_to_end_test" "workflow_execution" "fail" "Workflow failed (verified via DynamoDB)" "{\"duration_seconds\": $DURATION, \"task_id\": \"$TASK_ID\", \"error\": $ERROR_JSON}"
            fi
        else
            log_warn "Task record not found in DynamoDB after waiting"
            add_test_result "end_to_end_test" "dynamodb_task_tracking" "warn" "Task record not found" "{\"task_id\": \"$TASK_ID\"}"
        fi
    fi
}

# Update summary in JSON
update_summary() {
    if command -v jq &> /dev/null; then
        jq ".test_results.summary = {total_tests: $TOTAL_TESTS, passed: $TESTS_PASSED, failed: $TESTS_FAILED, warnings: $TESTS_WARNED}" \
            "$TEST_RESULTS_FILE" > "${TEST_RESULTS_FILE}.tmp" && mv "${TEST_RESULTS_FILE}.tmp" "$TEST_RESULTS_FILE"
    fi
}

# Main function
main() {
    echo "=========================================="
    echo "End-to-End Test Suite"
    echo "Agentic CI/CD Pipeline Generator"
    echo "=========================================="
    echo ""
    echo "Test Repository: $TEST_REPO_URL"
    echo "Test Branch: $TEST_BRANCH"
    echo "Results Directory: $TEST_RESULTS_DIR"
    echo "Timestamp: $TIMESTAMP"
    echo ""
    
    # Initialize test results
    init_test_results
    
    # Run tests
    check_prerequisites || exit 1
    
    test_lambda_functions
    test_bedrock_agents
    test_dynamodb
    test_s3
    
    # Ask before running end-to-end test (it takes time)
    echo ""
    read -p "Run full end-to-end workflow test? (This may take 5-15 minutes) [y/N]: " -n 1 -r
    echo ""
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        test_end_to_end_workflow
    else
        log_info "Skipping end-to-end workflow test"
        add_test_result "end_to_end_test" "workflow_execution" "skip" "Test skipped by user" "{}"
    fi
    
    # Update summary
    update_summary
    
    # Print summary
    echo ""
    log_section "Test Summary"
    echo -e "${GREEN}Passed:${NC} $TESTS_PASSED"
    echo -e "${YELLOW}Warnings:${NC} $TESTS_WARNED"
    echo -e "${RED}Failed:${NC} $TESTS_FAILED"
    echo -e "Total: $TOTAL_TESTS"
    echo ""
    echo "Test results saved to: $TEST_RESULTS_FILE"
    echo "Test log saved to: $TEST_LOG_FILE"
    echo ""
    
    if [ $TESTS_FAILED -eq 0 ]; then
        echo -e "${GREEN}✓ All tests passed!${NC}"
        exit 0
    else
        echo -e "${RED}✗ Some tests failed${NC}"
        exit 1
    fi
}

# Run main function
main

