# Deployment Notes for agent_prompts Module

## Issue

When deploying the Lambda function, you may encounter:

```
Runtime.ImportModuleError: Unable to import module 'orchestrator': No module named 'agent_prompts'
```

## Solution

The build scripts have been updated to include the `agent_prompts` directory in the Lambda deployment package.

## Updated Files

1. **`scripts/build_lambda.sh`** - Added step to copy `agent_prompts` directory
2. **`main.tf`** - Updated Terraform data source to copy `agent_prompts` directory

## How It Works

The build process now:

1. Copies all `*.py` files from `lambda/` to `build/lambda_package/`
2. **Copies the `agent_prompts/` directory** (new step)
3. Installs dependencies from `requirements.txt`
4. Creates a ZIP file with all files and directories

## Deployment Steps

After making changes to prompts:

1. **Rebuild the Lambda package:**

   ```bash
   ./scripts/build_lambda.sh
   ```

   Or let Terraform handle it:

   ```bash
   terraform plan
   terraform apply
   ```

2. **Verify the package includes agent_prompts:**

   ```bash
   unzip -l build/lambda_functions.zip | grep agent_prompts
   ```

   You should see entries like:

   ```
   agent_prompts/__init__.py
   agent_prompts/prompt_loader.py
   agent_prompts/repo_scanner.txt
   ...
   ```

3. **Deploy:**
   ```bash
   terraform apply
   ```

## Verification

After deployment, the Lambda function should be able to import:

```python
from agent_prompts.prompt_loader import format_prompt
```

## Troubleshooting

If you still see import errors:

1. **Check the ZIP file contents:**

   ```bash
   unzip -l build/lambda_functions.zip | grep -E "(agent_prompts|orchestrator)"
   ```

2. **Verify the directory structure in the ZIP:**

   ```bash
   unzip -l build/lambda_functions.zip | head -20
   ```

3. **Ensure `__init__.py` exists:**

   ```bash
   ls -la lambda/agent_prompts/__init__.py
   ```

4. **Rebuild from scratch:**
   ```bash
   rm -rf build/
   ./scripts/build_lambda.sh
   terraform apply
   ```

## Notes

- The `agent_prompts` directory must be at the same level as `orchestrator.py` in the ZIP file
- All `.txt` prompt files must be included in the package
- The `__init__.py` file makes `agent_prompts` a Python package
- The zip creation script uses `os.walk()` which automatically includes subdirectories
