#!/bin/bash

# Script to trigger GitHub workflow generation for a target repository
# This script prompts for repository URL and invokes the orchestrator agent

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Configuration
CLI_READ_TIMEOUT="${CLI_READ_TIMEOUT:-1200}"  # 20 minutes
CLI_CONNECT_TIMEOUT="${CLI_CONNECT_TIMEOUT:-60}"  # 1 minute
DEFAULT_BRANCH="main"

# Logging functions
log_info() {
    echo -e "${BLUE}ℹ${NC} $1"
}

log_success() {
    echo -e "${GREEN}✓${NC} $1"
}

log_error() {
    echo -e "${RED}✗${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}⚠${NC} $1"
}

log_section() {
    echo ""
    echo -e "${CYAN}==========================================${NC}"
    echo -e "${CYAN}$1${NC}"
    echo -e "${CYAN}==========================================${NC}"
    echo ""
}

# Validate GitHub repository URL
validate_repo_url() {
    local url="$1"
    
    # Remove trailing slash and .git if present
    url="${url%/}"
    url="${url%.git}"
    
    # Check if it's a valid GitHub URL
    if [[ "$url" =~ ^https://github\.com/[^/]+/[^/]+$ ]] || \
       [[ "$url" =~ ^git@github\.com:[^/]+/[^/]+$ ]]; then
        return 0
    fi
    
    return 1
}

# Parse repository owner and name from URL
parse_repo_info() {
    local url="$1"
    local cleaned="${url%/}"
    cleaned="${cleaned%.git}"
    cleaned="${cleaned#git@github.com:}"
    cleaned="${cleaned#https://github.com/}"
    
    REPO_OWNER=$(echo "$cleaned" | cut -d'/' -f1)
    REPO_NAME=$(echo "$cleaned" | cut -d'/' -f2)
}

# Check prerequisites
check_prerequisites() {
    log_section "Checking Prerequisites"
    
    # Check AWS CLI
    if ! command -v aws &> /dev/null; then
        log_error "AWS CLI not installed"
        exit 1
    fi
    log_success "AWS CLI installed"
    
    # Check AWS credentials
    if ! aws sts get-caller-identity &> /dev/null; then
        log_error "AWS credentials not configured"
        exit 1
    fi
    AWS_ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
    log_success "AWS credentials configured (Account: $AWS_ACCOUNT)"
    
    # Check Terraform
    if ! command -v terraform &> /dev/null; then
        log_error "Terraform not installed"
        exit 1
    fi
    log_success "Terraform installed"
    
    # Check Terraform outputs
    if ! terraform output -json &> /dev/null; then
        log_error "Terraform outputs not available - run 'terraform apply' first"
        exit 1
    fi
    log_success "Terraform outputs available"
    
    # Check jq (optional but recommended)
    if command -v jq &> /dev/null; then
        log_success "jq installed (for JSON processing)"
        HAS_JQ=true
    else
        log_warn "jq not installed (JSON processing will be limited)"
        HAS_JQ=false
    fi
}

# Get Terraform outputs
get_terraform_outputs() {
    log_section "Retrieving Infrastructure Information"
    
    LAMBDA_ORCHESTRATOR=$(terraform output -raw lambda_orchestrator 2>/dev/null || echo "")
    if [ -z "$LAMBDA_ORCHESTRATOR" ]; then
        log_error "Orchestrator Lambda name not found in Terraform outputs"
        exit 1
    fi
    log_success "Orchestrator Lambda: $LAMBDA_ORCHESTRATOR"
    
    AGENT_IDS=$(terraform output -json agent_ids_map 2>/dev/null || echo "{}")
    if [ "$AGENT_IDS" = "{}" ]; then
        log_error "Agent IDs not found in Terraform outputs"
        exit 1
    fi
    log_success "Agent IDs retrieved"
    
    # Display agent IDs if jq is available
    if [ "$HAS_JQ" = true ]; then
        echo ""
        log_info "Available agents:"
        echo "$AGENT_IDS" | jq -r 'to_entries[] | "  - \(.key): \(.value)"'
    fi
}

# Prompt for repository URL
prompt_repo_url() {
    log_section "Repository Information"
    
    while true; do
        read -p "Enter GitHub repository URL: " REPO_URL
        
        if [ -z "$REPO_URL" ]; then
            log_error "Repository URL cannot be empty"
            continue
        fi
        
        if validate_repo_url "$REPO_URL"; then
            parse_repo_info "$REPO_URL"
            log_success "Repository URL validated: $REPO_URL"
            log_info "Owner: $REPO_OWNER"
            log_info "Repository: $REPO_NAME"
            break
        else
            log_error "Invalid GitHub repository URL"
            log_info "Expected format: https://github.com/owner/repo or git@github.com:owner/repo"
        fi
    done
    
    # Prompt for branch (optional)
    read -p "Enter branch name [default: $DEFAULT_BRANCH]: " BRANCH
    BRANCH="${BRANCH:-$DEFAULT_BRANCH}"
    log_success "Target branch: $BRANCH"
}

# Create task ID
generate_task_id() {
    # Generate a unique task ID with timestamp and random component
    if command -v openssl &> /dev/null; then
        RANDOM_HEX=$(openssl rand -hex 4 2>/dev/null || echo $(head -c 4 /dev/urandom | od -An -tx1 | tr -d ' \n'))
    elif [ -c /dev/urandom ]; then
        RANDOM_HEX=$(head -c 4 /dev/urandom | od -An -tx1 | tr -d ' \n')
    else
        RANDOM_HEX=$(printf "%04x" $RANDOM)
    fi
    TASK_ID="workflow-gen-$(date +%s)-${RANDOM_HEX}"
    log_info "Task ID: $TASK_ID"
}

# Create payload
create_payload() {
    if [ "$HAS_JQ" = true ]; then
        PAYLOAD=$(jq -n \
            --arg task_id "$TASK_ID" \
            --arg repo_url "$REPO_URL" \
            --arg branch "$BRANCH" \
            --argjson agent_ids "$AGENT_IDS" \
            '{task_id: $task_id, repo_url: $repo_url, branch: $branch, agent_ids: $agent_ids}')
    else
        # Fallback if jq is not available
        PAYLOAD="{\"task_id\": \"$TASK_ID\", \"repo_url\": \"$REPO_URL\", \"branch\": \"$BRANCH\", \"agent_ids\": $AGENT_IDS}"
    fi
}

# Cleanup function to restore cursor
cleanup_cursor() {
    tput cnorm 2>/dev/null || true
}

# Map step names to agent/component names
get_agent_name() {
    local step_name="$1"
    case "$step_name" in
        "repo_ingestor")
            echo "Repository Ingestor Lambda"
            ;;
        "repo_scanner")
            echo "Repo Scanner Agent"
            ;;
        "static_analyzer")
            echo "Static Analyzer Lambda"
            ;;
        "pipeline_designer")
            echo "Pipeline Designer Agent"
            ;;
        "security_compliance")
            echo "Security & Compliance Agent"
            ;;
        "yaml_generator_attempt_1"|"yaml_generator_attempt_2")
            echo "YAML Generator Agent"
            ;;
        "template_validator")
            echo "Template Validator Lambda"
            ;;
        "pr_manager")
            echo "PR Manager Agent"
            ;;
        "github_operations")
            echo "GitHub API Lambda"
            ;;
        *)
            echo "$step_name"
            ;;
    esac
}

# Get next expected step
get_next_step() {
    local completed_steps="$1"
    local expected_steps=(
        "repo_ingestor"
        "repo_scanner"
        "static_analyzer"
        "pipeline_designer"
        "security_compliance"
        "yaml_generator_attempt_1"
        "yaml_generator_attempt_2"
        "template_validator"
        "pr_manager"
        "github_operations"
    )
    
    for step in "${expected_steps[@]}"; do
        if ! echo "$completed_steps" | grep -q "^${step}$"; then
            echo "$step"
            return
        fi
    done
    echo ""
}

# Poll DynamoDB for task progress
poll_task_progress() {
    local table_name="$1"
    local task_id="$2"
    local start_time="$3"
    local poll_interval=5  # Poll every 5 seconds
    local max_wait=1200    # Maximum 20 minutes
    local elapsed=0
    
    # Set up trap to restore cursor on exit
    trap cleanup_cursor EXIT INT TERM
    
    echo ""
    log_info "Starting progress monitor (polling every ${poll_interval}s)..."
    sleep 1  # Brief pause before starting to clear screen
    
    # Hide cursor for cleaner display
    if [ -t 1 ]; then
        tput civis 2>/dev/null || true
        # Clear screen before starting
        clear 2>/dev/null || echo -ne "\033[2J\033[H"
    fi
    
    while [ $elapsed -lt $max_wait ]; do
        # Get task record from DynamoDB
        if aws dynamodb get-item \
            --table-name "$table_name" \
            --key "{\"task_id\": {\"S\": \"$task_id\"}}" \
            --output json > /tmp/task_record_${task_id}.json 2>/dev/null; then
            
            # Parse task status
            local task_status=$(jq -r '.Item.status.S // "unknown"' /tmp/task_record_${task_id}.json 2>/dev/null || echo "unknown")
            local task_result=$(jq -r '.Item.result.S // "{}"' /tmp/task_record_${task_id}.json 2>/dev/null || echo "{}")
            
            # Calculate elapsed time
            local current_time=$(date +%s)
            local elapsed_seconds=$((current_time - start_time))
            local elapsed_min=$((elapsed_seconds / 60))
            local elapsed_sec=$((elapsed_seconds % 60))
            
            # Clear previous output - use multiple methods for reliability
            if [ -t 1 ]; then
                # Clear screen and move cursor to top
                clear 2>/dev/null || echo -ne "\033[2J\033[H"
                # Also try tput method as backup
                if command -v tput &> /dev/null; then
                    tput cup 0 0 2>/dev/null || true
                fi
            else
                # Not a terminal, just print newlines
                echo ""
            fi
            
            # Display header
            echo -e "${BLUE}==============================================================${NC}"
            echo -e "${BLUE}Workflow Generation Progress${NC}"
            echo -e "${BLUE}==============================================================${NC}"
            echo ""
            echo -e "Task ID:     ${YELLOW}$task_id${NC}"
            echo -e "Repository:  ${YELLOW}$REPO_URL${NC}"
            echo -e "Branch:      ${YELLOW}$BRANCH${NC}"
            echo -e "Status:      $(format_status "$task_status")"
            echo -e "Elapsed:     ${YELLOW}${elapsed_min}m ${elapsed_sec}s${NC}"
            echo ""
            
            # Parse and display workflow steps
            if [ "$task_result" != "{}" ] && [ "$task_result" != "null" ] && [ -n "$task_result" ]; then
                if [ "$HAS_JQ" = true ]; then
                    local steps_json=$(echo "$task_result" | jq '.steps // []' 2>/dev/null || echo "[]")
                    local step_count=$(echo "$steps_json" | jq 'length' 2>/dev/null || echo "0")
                else
                    # Fallback without jq - try to count steps manually
                    local step_count=$(echo "$task_result" | grep -o '"step"' | wc -l 2>/dev/null || echo "0")
                    local steps_json="[]"
                fi
                
                if [ "$step_count" -gt 0 ] && [ "$HAS_JQ" = true ]; then
                    # Determine currently running agent
                    local completed_step_names=$(echo "$steps_json" | jq -r '.[].step' 2>/dev/null || echo "")
                    local next_step=$(get_next_step "$completed_step_names")
                    local current_agent=""
                    
                    if [ -n "$next_step" ]; then
                        current_agent=$(get_agent_name "$next_step")
                    fi
                    
                    # Show currently running agent
                    if [ -n "$current_agent" ] && [ "$task_status" = "in_progress" ]; then
                        echo -e "${CYAN}Currently Running:${NC}"
                        echo -e "  ${YELLOW}→${NC} ${CYAN}$current_agent${NC}"
                        echo ""
                    fi
                    
                    # Display completed steps
                    echo -e "${BLUE}Completed Steps:${NC}"
                    for i in $(seq 0 $((step_count - 1))); do
                        local step_name=$(echo "$steps_json" | jq -r ".[$i].step // \"unknown\"" 2>/dev/null || echo "unknown")
                        local step_result=$(echo "$steps_json" | jq -r ".[$i].result // {}" 2>/dev/null || echo "{}")
                        local step_status=$(echo "$step_result" | jq -r '.status // "unknown"' 2>/dev/null || echo "unknown")
                        local agent_name=$(get_agent_name "$step_name")
                        
                        case "$step_status" in
                            "success")
                                echo -e "  ${GREEN}✓${NC} $agent_name"
                                ;;
                            "error")
                                echo -e "  ${RED}✗${NC} $agent_name ${RED}(failed)${NC}"
                                ;;
                            *)
                                echo -e "  ${YELLOW}○${NC} $agent_name ${YELLOW}(in progress)${NC}"
                                ;;
                        esac
                    done
                elif [ "$step_count" -gt 0 ]; then
                    echo -e "${BLUE}Completed Steps:${NC} ${step_count} step(s)"
                    echo -e "${YELLOW}(Install jq for detailed step information)${NC}"
                else
                    echo -e "${YELLOW}Waiting for workflow to start...${NC}"
                fi
            else
                echo -e "${YELLOW}Initializing workflow...${NC}"
            fi
            
            echo ""
            echo -e "${BLUE}==============================================================${NC}"
            echo -e "${BLUE}Press Ctrl+C to stop monitoring (workflow will continue)${NC}"
            
            # Check if task is complete
            if [ "$task_status" = "completed" ] || [ "$task_status" = "failed" ]; then
                tput cnorm 2>/dev/null || true
                echo ""
                return 0
            fi
        else
            # Task record not found yet
            if [ -t 1 ]; then
                # Clear screen and move cursor to top
                clear 2>/dev/null || echo -ne "\033[2J\033[H"
                # Also try tput method as backup
                if command -v tput &> /dev/null; then
                    tput cup 0 0 2>/dev/null || true
                fi
            else
                # Not a terminal, just print newlines
                echo ""
            fi
            echo -e "${BLUE}==============================================================${NC}"
            echo -e "${BLUE}Workflow Generation Progress${NC}"
            echo -e "${BLUE}==============================================================${NC}"
            echo ""
            echo -e "Task ID:     ${YELLOW}$task_id${NC}"
            echo -e "${YELLOW}Waiting for task to be created in DynamoDB...${NC}"
            local current_time=$(date +%s)
            local elapsed_seconds=$((current_time - start_time))
            local elapsed_min=$((elapsed_seconds / 60))
            local elapsed_sec=$((elapsed_seconds % 60))
            echo -e "Elapsed:     ${YELLOW}${elapsed_min}m ${elapsed_sec}s${NC}"
            echo ""
        fi
        
        sleep $poll_interval
        elapsed=$((elapsed + poll_interval))
    done
    
    # Show cursor again
    tput cnorm 2>/dev/null || true
    echo ""
    log_warn "Maximum wait time reached. Task may still be in progress."
    return 1
}

# Format status for display
format_status() {
    local status="$1"
    case "$status" in
        "in_progress")
            echo -e "${YELLOW}IN PROGRESS${NC}"
            ;;
        "completed")
            echo -e "${GREEN}COMPLETED${NC}"
            ;;
        "failed")
            echo -e "${RED}FAILED${NC}"
            ;;
        *)
            echo -e "${BLUE}${status}${NC}"
            ;;
    esac
}

# Invoke orchestrator
invoke_orchestrator() {
    log_section "Invoking Orchestrator Agent"
    
    log_info "This may take 5-15 minutes to complete..."
    log_info "The orchestrator will:"
    echo "  1. Analyze the repository structure"
    echo "  2. Design a CI/CD pipeline"
    echo "  3. Perform security and compliance checks"
    echo "  4. Generate GitHub Actions workflow YAML"
    echo "  5. Create a pull request with the workflow"
    echo ""
    
    # Get DynamoDB table name
    TABLE_NAME=$(terraform output -raw dynamodb_table 2>/dev/null || echo "")
    if [ -z "$TABLE_NAME" ]; then
        log_error "DynamoDB table name not found in Terraform outputs"
        exit 1
    fi
    
    # Create temporary response file
    RESPONSE_FILE="/tmp/orchestrator_response_${TASK_ID}.json"
    
    START_TIME=$(date +%s)
    
    log_info "Invoking orchestrator Lambda..."
    log_info "Task ID: $TASK_ID"
    log_info "Repository: $REPO_URL"
    log_info "Branch: $BRANCH"
    echo ""
    
    # Invoke Lambda asynchronously in background
    log_info "Invoking orchestrator (running in background)..."
    if aws lambda invoke \
        --function-name "$LAMBDA_ORCHESTRATOR" \
        --invocation-type Event \
        --cli-binary-format raw-in-base64-out \
        --payload "$PAYLOAD" \
        "$RESPONSE_FILE" 2>&1 > /dev/null; then
        
        log_success "Orchestrator Lambda invoked successfully"
        echo ""
        
        # Start progress monitoring
        poll_task_progress "$TABLE_NAME" "$TASK_ID" "$START_TIME"
        POLL_EXIT_CODE=$?
        
        # Get final task status
        if [ -f /tmp/task_record_${TASK_ID}.json ]; then
            FINAL_STATUS=$(jq -r '.Item.status.S // "unknown"' /tmp/task_record_${TASK_ID}.json 2>/dev/null || echo "unknown")
            FINAL_RESULT=$(jq -r '.Item.result.S // "{}"' /tmp/task_record_${TASK_ID}.json 2>/dev/null || echo "{}")
            
            END_TIME=$(date +%s)
            DURATION=$((END_TIME - START_TIME))
            
            echo ""
            log_section "Final Results"
            
            if [ "$FINAL_STATUS" = "completed" ]; then
                log_success "Workflow generation completed successfully! (duration: ${DURATION}s)"
                echo ""
                
                # Display workflow steps summary
                if [ "$FINAL_RESULT" != "{}" ] && [ "$FINAL_RESULT" != "null" ]; then
                    WORKFLOW_STEPS=$(echo "$FINAL_RESULT" | jq '.steps // []' 2>/dev/null || echo "[]")
                    STEP_COUNT=$(echo "$WORKFLOW_STEPS" | jq 'length' 2>/dev/null || echo "0")
                    
                    if [ "$STEP_COUNT" -gt 0 ]; then
                        log_info "Workflow steps completed: $STEP_COUNT"
                        echo ""
                        for i in $(seq 0 $((STEP_COUNT - 1))); do
                            STEP_NAME=$(echo "$WORKFLOW_STEPS" | jq -r ".[$i].step // \"unknown\"" 2>/dev/null || echo "unknown")
                            STEP_STATUS=$(echo "$WORKFLOW_STEPS" | jq -r ".[$i].result.status // \"unknown\"" 2>/dev/null || echo "unknown")
                            
                            if [ "$STEP_STATUS" = "success" ]; then
                                echo -e "  ${GREEN}✓${NC} $STEP_NAME"
                            else
                                echo -e "  ${YELLOW}⚠${NC} $STEP_NAME - $STEP_STATUS"
                            fi
                        done
                        echo ""
                    fi
                    
                    # Check for GitHub operations
                    GITHUB_STEP=$(echo "$WORKFLOW_STEPS" | jq '.[] | select(.step == "github_operations")' 2>/dev/null || echo "")
                    if [ -n "$GITHUB_STEP" ]; then
                        GITHUB_SUCCESS=$(echo "$GITHUB_STEP" | jq -r '.result.success // false' 2>/dev/null || echo "false")
                        if [ "$GITHUB_SUCCESS" = "true" ]; then
                            log_success "GitHub pull request created successfully!"
                            log_info "Check the repository for the new PR with the generated workflow"
                        else
                            GITHUB_ERROR=$(echo "$GITHUB_STEP" | jq -r '.result.error // "Unknown error"' 2>/dev/null || echo "Unknown error")
                            log_warn "GitHub operations may have encountered issues: $GITHUB_ERROR"
                        fi
                    fi
                fi
                
            elif [ "$FINAL_STATUS" = "failed" ]; then
                ERROR_MSG=$(echo "$FINAL_RESULT" | jq -r '.error // "Unknown error"' 2>/dev/null || echo "Unknown error")
                log_error "Workflow generation failed: $ERROR_MSG"
                echo ""
                log_info "Check CloudWatch logs for the orchestrator Lambda function for more details"
            else
                log_warn "Task status: $FINAL_STATUS"
                log_info "The task may still be in progress. Check DynamoDB table for latest status."
            fi
            
            # Display task ID for tracking
            echo ""
            log_info "Task ID for tracking: $TASK_ID"
            log_info "You can check the DynamoDB table '$TABLE_NAME' for detailed task status"
            
        else
            log_warn "Could not retrieve final task status from DynamoDB"
            log_info "Task ID: $TASK_ID"
            log_info "Check the DynamoDB table '$TABLE_NAME' manually"
        fi
        
    else
        log_error "Orchestrator Lambda invocation failed"
        log_info "Check AWS credentials and Lambda function permissions"
        log_info "Task ID: $TASK_ID"
        exit 1
    fi
}

# Main function
main() {
    echo ""
    log_section "GitHub Workflow Generation Trigger"
    echo "This script will trigger the orchestrator agent to generate"
    echo "GitHub Actions workflows for your target repository."
    echo ""
    
    # Check prerequisites
    check_prerequisites
    
    # Get Terraform outputs
    get_terraform_outputs
    
    # Prompt for repository information
    prompt_repo_url
    
    # Generate task ID
    generate_task_id
    
    # Create payload
    create_payload
    
    # Confirm before proceeding
    echo ""
    log_section "Confirmation"
    echo "Repository: $REPO_URL"
    echo "Branch: $BRANCH"
    echo "Task ID: $TASK_ID"
    echo ""
    read -p "Proceed with workflow generation? [y/N]: " -n 1 -r
    echo ""
    
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        log_info "Operation cancelled"
        exit 0
    fi
    
    # Invoke orchestrator
    invoke_orchestrator
    
    echo ""
    log_success "Script completed"
}

# Run main function
main

