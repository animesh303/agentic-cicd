# End-to-End Testing Guide
## Agentic CI/CD Pipeline Generator

This guide explains how to perform comprehensive end-to-end testing of the Agentic CI/CD Pipeline Generator solution.

---

## Overview

The end-to-end test suite validates:

1. **Prerequisites** - Required tools and configurations
2. **Component Tests** - Individual Lambda functions and Bedrock agents
3. **Integration Tests** - Component interactions
4. **End-to-End Workflow** - Complete pipeline generation workflow

---

## Prerequisites

### Required Tools

- **AWS CLI** - Version 2.x or later
- **Terraform** - Version 1.5 or later
- **jq** - JSON processor (recommended)
- **Bash** - Version 4.0 or later

### Required Access

- AWS account with appropriate permissions
- Terraform state access (if using remote state)
- GitHub repository access (for testing)

### Required Configuration

1. **AWS Credentials**
   ```bash
   aws configure
   # Or use environment variables:
   export AWS_ACCESS_KEY_ID=...
   export AWS_SECRET_ACCESS_KEY=...
   export AWS_DEFAULT_REGION=us-east-1
   ```

2. **Terraform State**
   ```bash
   terraform init -backend-config=backend.tfvars
   ```

3. **Deployed Infrastructure**
   ```bash
   terraform apply
   ```

---

## Running the Test Suite

### Quick Start

```bash
# Make script executable (if not already)
chmod +x scripts/e2e_test.sh

# Run with default settings
./scripts/e2e_test.sh
```

### Custom Configuration

```bash
# Set custom test repository
export TEST_REPO_URL="https://github.com/your-org/your-repo"
export TEST_BRANCH="main"

# Set custom results directory
export TEST_RESULTS_DIR="./my_test_results"

# Run tests
./scripts/e2e_test.sh
```

### Test Options

The script supports the following environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `TEST_REPO_URL` | `https://github.com/octocat/Hello-World` | Repository to test with |
| `TEST_BRANCH` | `main` | Branch to test |
| `TEST_RESULTS_DIR` | `./test_results` | Directory for test results |

---

## Test Phases

### Phase 1: Prerequisites Check

Validates that all required tools and configurations are in place.

**What it checks:**
- AWS CLI installation and credentials
- Terraform installation
- Terraform outputs availability
- jq installation (optional)

**Expected Duration:** < 10 seconds

**Success Criteria:**
- All prerequisites pass
- AWS credentials are valid
- Terraform outputs are available

---

### Phase 2: Component Tests

Tests individual components in isolation.

#### Lambda Function Tests

**Repository Ingestor**
- Tests repository download and manifest extraction
- Validates response format

**Static Analyzer**
- Tests Dockerfile analysis
- Tests dependency analysis
- Tests test framework detection

**Template Validator**
- Tests YAML validation
- Validates syntax checking
- Validates security checks

**Expected Duration:** 30-60 seconds per function

#### Bedrock Agent Tests

**Repo Scanner Agent**
- Tests agent invocation
- Validates response streaming
- Checks action group integration

**Expected Duration:** 30-60 seconds (may timeout for long responses)

#### Infrastructure Tests

**DynamoDB**
- Tests table existence
- Tests write operations
- Tests read operations

**S3 Bucket**
- Tests bucket existence
- Validates OpenAPI specs presence

**Expected Duration:** 10-20 seconds

---

### Phase 3: End-to-End Workflow Test

Tests the complete workflow from repository analysis to PR creation.

**Workflow Steps:**

1. **Repository Scanner Agent**
   - Analyzes repository structure
   - Extracts manifest files
   - Identifies languages and frameworks

2. **Static Analyzer Lambda**
   - Analyzes Dockerfiles
   - Analyzes dependencies
   - Detects test frameworks

3. **Pipeline Designer Agent**
   - Designs CI/CD pipeline
   - Defines build/test/deploy stages

4. **Security & Compliance Agent**
   - Reviews pipeline design
   - Ensures security best practices
   - Validates compliance requirements

5. **YAML Generator Agent**
   - Generates GitHub Actions YAML
   - Includes AWS credentials configuration
   - Manages secrets properly

6. **Template Validator Lambda**
   - Validates YAML syntax
   - Checks security issues
   - Validates IAM permissions

7. **PR Manager Agent**
   - Creates GitHub branch
   - Commits workflow files
   - Creates draft pull request

**Expected Duration:** 5-15 minutes

**Success Criteria:**
- All workflow steps complete successfully
- Task record created in DynamoDB
- YAML generated and validated
- PR created (if GitHub PAT configured)

---

## Test Results

### Output Files

The test script generates the following files:

1. **Test Results JSON** (`e2e_test_results_[timestamp].json`)
   - Structured test results in JSON format
   - Includes all test outcomes and details

2. **Test Log** (`e2e_test_log_[timestamp].log`)
   - Detailed execution log
   - Includes all output and errors

3. **Orchestrator Response** (`orchestrator_response_[timestamp].json`)
   - Full orchestrator Lambda response
   - Includes all workflow step results

4. **Task Record** (`task_record_[timestamp].json`) (if applicable)
   - DynamoDB task record
   - Task status and metadata

### Interpreting Results

#### Test Status Indicators

- ✅ **Pass** - Test completed successfully
- ⚠️ **Warn** - Test completed with warnings
- ❌ **Fail** - Test failed

#### Summary Metrics

- **Total Tests** - Number of tests executed
- **Passed** - Number of successful tests
- **Failed** - Number of failed tests
- **Warnings** - Number of tests with warnings

---

## Troubleshooting

### Common Issues

#### 1. AWS Credentials Not Configured

**Error:**
```
✗ AWS credentials not configured
```

**Solution:**
```bash
aws configure
# Or set environment variables
export AWS_ACCESS_KEY_ID=...
export AWS_SECRET_ACCESS_KEY=...
```

#### 2. Terraform Outputs Not Available

**Error:**
```
✗ Terraform outputs not available
```

**Solution:**
```bash
# Ensure Terraform is initialized
terraform init -backend-config=backend.tfvars

# Ensure infrastructure is deployed
terraform apply

# Verify outputs
terraform output
```

#### 3. Lambda Function Not Found

**Error:**
```
✗ Lambda function does not exist
```

**Solution:**
- Verify Terraform deployment completed successfully
- Check Lambda function names in Terraform outputs
- Ensure you're in the correct AWS region

#### 4. Bedrock Agent Timeout

**Warning:**
```
⚠ Bedrock agent test timed out
```

**Solution:**
- This is normal for long-running agent invocations
- Check CloudWatch logs for agent execution details
- Verify agent is properly configured

#### 5. GitHub PAT Not Configured

**Warning:**
```
⚠ GitHub PAT secret contains placeholder value
```

**Solution:**
```bash
# Update GitHub PAT in Secrets Manager
aws secretsmanager update-secret \
  --secret-id bedrock/github/pat \
  --secret-string '{"token":"YOUR_GITHUB_PAT"}'
```

#### 6. End-to-End Test Fails

**Possible Causes:**
- Agent IDs not configured correctly
- GitHub PAT not set or invalid
- Repository access issues
- Network/timeout issues

**Debugging:**
```bash
# Check CloudWatch logs
aws logs tail /aws/lambda/[orchestrator-function-name] --follow

# Check DynamoDB task record
aws dynamodb get-item \
  --table-name [table-name] \
  --key '{"task_id":{"S":"[task-id]"}}'

# Check agent status
aws bedrock-agent get-agent --agent-id [agent-id]
```

---

## Best Practices

### Before Running Tests

1. **Verify Infrastructure**
   ```bash
   terraform plan
   terraform apply
   ```

2. **Check Prerequisites**
   ```bash
   aws sts get-caller-identity
   terraform output
   ```

3. **Update GitHub PAT**
   ```bash
   # If using GitHub integration
   aws secretsmanager update-secret \
     --secret-id bedrock/github/pat \
     --secret-string '{"token":"YOUR_TOKEN"}'
   ```

### During Testing

1. **Monitor CloudWatch Logs**
   - Keep CloudWatch console open
   - Watch for errors in real-time

2. **Check Resource Usage**
   - Monitor Lambda invocations
   - Check Bedrock service quotas
   - Watch DynamoDB metrics

3. **Save Test Results**
   - Review generated JSON files
   - Keep logs for troubleshooting

### After Testing

1. **Review Test Results**
   - Check summary metrics
   - Review failed tests
   - Address warnings

2. **Clean Up Test Data**
   ```bash
   # Remove test task records (optional)
   aws dynamodb delete-item \
     --table-name [table-name] \
     --key '{"task_id":{"S":"[test-task-id]"}}'
   ```

3. **Document Issues**
   - Record any failures
   - Document workarounds
   - Update test documentation

---

## Continuous Testing

### Automated Testing

For CI/CD integration:

```bash
# Run tests in CI pipeline
./scripts/e2e_test.sh

# Check exit code
if [ $? -eq 0 ]; then
  echo "All tests passed"
else
  echo "Tests failed"
  exit 1
fi
```

### Scheduled Testing

Set up scheduled tests to validate system health:

```bash
# Add to cron (daily at 2 AM)
0 2 * * * /path/to/scripts/e2e_test.sh >> /var/log/e2e_tests.log 2>&1
```

---

## Test Coverage

### Current Coverage

- ✅ Prerequisites validation
- ✅ Lambda function invocation
- ✅ Bedrock agent invocation
- ✅ DynamoDB operations
- ✅ S3 bucket validation
- ✅ End-to-end workflow
- ✅ Task tracking

### Future Enhancements

- [ ] Performance benchmarking
- [ ] Load testing
- [ ] Error injection testing
- [ ] Security testing
- [ ] Multi-repository testing

---

## Related Documentation

- [Validation Guide](./VALIDATION.md) - Detailed validation steps
- [Architecture Documentation](./ARCHITECTURE.md) - System architecture
- [Requirements Document](./REQUIREMENTS.md) - System requirements
- [Test Results Template](./E2E_TEST_RESULTS.md) - Test results documentation

---

## Support

For issues or questions:

1. Check CloudWatch logs for detailed error messages
2. Review test log files in `test_results/` directory
3. Consult troubleshooting section above
4. Review architecture and validation documentation

---

**Last Updated:** [Date]  
**Test Script Version:** 1.0

