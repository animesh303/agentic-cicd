# Agent Prompts Module

This directory contains all agent prompts used by the orchestrator Lambda function. Prompts are stored as separate template files for easier management and version control.

## Structure

```
agent_prompts/
├── __init__.py              # Module initialization
├── prompt_loader.py         # Utility for loading and formatting prompts
├── repo_scanner.txt         # Repository scanner agent prompt
├── pipeline_designer.txt    # Pipeline designer agent prompt
├── security_compliance.txt  # Security & compliance agent prompt
├── yaml_generator_base.txt  # YAML generator base prompt
├── yaml_generator_retry.txt # YAML generator retry prompt
├── pr_manager.txt          # PR manager agent prompt
└── pr_body_default.txt     # Default PR body template
```

## Usage

### Loading a Prompt

```python
from agent_prompts.prompt_loader import format_prompt

# Format a prompt with variables
prompt = format_prompt(
    "repo_scanner",
    repo_url="https://github.com/owner/repo",
    branch="main",
    manifest_context="..."
)
```

### Available Prompts

1. **repo_scanner** - Analyzes repository structure and identifies technologies
   - Variables: `repo_url`, `branch`, `manifest_context`

2. **pipeline_designer** - Designs CI/CD pipeline stages
   - Variables: `repo_analysis`

3. **security_compliance** - Reviews pipeline for security and compliance
   - Variables: `pipeline_design`, `analysis_context`

4. **yaml_generator_base** - Generates GitHub Actions workflow YAML
   - Variables: `pipeline_design`

5. **yaml_generator_retry** - Retry prompt for YAML generation
   - Variables: `base_prompt`

6. **pr_manager** - Generates PR description
   - Variables: `repo_url`, `branch`, `pipeline_summary`, `security_summary`, `yaml_section`

7. **pr_body_default** - Default PR body template
   - Variables: `timestamp`

## Adding or Modifying Prompts

1. **Create/Edit Template File**: Add or modify a `.txt` file in this directory
2. **Use Placeholders**: Use Python string formatting placeholders like `{variable_name}`
3. **Update Orchestrator**: If adding a new prompt, update `orchestrator.py` to use `format_prompt()`
4. **Test**: Ensure all placeholders are provided when calling `format_prompt()`

## Template Format

Templates use Python's `.format()` method for variable substitution:

```
Analyze repository: {repo_url} (branch: {branch}).

Use the manifest data below...
{manifest_context}
```

## Benefits

- **Centralized Management**: All prompts in one location
- **Version Control**: Easy to track changes to prompts
- **Reusability**: Prompts can be shared across different functions
- **Maintainability**: Update prompts without modifying orchestrator code
- **Testing**: Easier to test prompt variations

## Example: Updating OIDC Authentication Rules

To update OIDC authentication requirements across all agents:

1. Edit `yaml_generator_base.txt` - Update YAML generation requirements
2. Edit `security_compliance.txt` - Update security review guidelines
3. Edit `pr_manager.txt` - Update PR description requirements
4. No need to modify `orchestrator.py` code

This makes it easy to maintain consistency across all agent prompts.

