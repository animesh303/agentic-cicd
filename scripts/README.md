# Build Scripts

## build_lambda.sh

Builds the Lambda functions deployment package.

### Usage

```bash
./scripts/build_lambda.sh
```

### What it does

1. Creates the build directory structure
2. Copies all Python files from `lambda/` directory
3. Installs dependencies from `lambda/requirements.txt` (Linux-compatible for Lambda runtime)
4. Creates a deployment package ZIP file at `build/lambda_functions.zip`

### Requirements

- Python 3.x
- pip
- Access to the `lambda/` directory with Python source files
- `lambda/requirements.txt` (optional, but recommended)

### Output

The script creates:

- `build/lambda_package/` - Temporary build directory (can be cleaned up)
- `build/lambda_functions.zip` - Final deployment package for all Lambda functions

### When to run

Run this script:

- Before running `terraform plan` or `terraform apply`
- After making changes to Lambda function code
- After updating `lambda/requirements.txt`
- In CI/CD pipelines before Terraform deployment

### Notes

- The script automatically handles platform-specific package installation for Lambda's Linux runtime
- The build directory is cleaned before each build
- The script exits with an error code if any step fails
