# Agent Prompts Module

This directory contains all agent prompts used by the orchestrator Lambda function. Prompts are stored as separate template files for easier management and version control.

## Structure

```
agent_prompts/
├── __init__.py                    # Module initialization
├── prompt_loader.py               # Utility for loading and formatting prompts
├── repo_scanner.txt               # Repository scanner agent prompt
├── pipeline_designer.txt           # Pipeline designer agent prompt
├── security_compliance.txt         # Security & compliance agent prompt
├── yaml_generator_ci.txt           # CI workflow generator prompt (ACTIVE)
├── yaml_generator_cd.txt            # CD workflow generator prompt (ACTIVE)
├── yaml_generator_base.txt          # ⚠️ OBSOLETE - Do not use
├── yaml_generator_retry.txt        # ⚠️ OBSOLETE - Do not use
├── pr_manager.txt                  # PR manager agent prompt
├── pr_body_default.txt             # Default PR body template
├── ecr_guidance_terraform.txt      # ECR Terraform guidance (used by CD prompt)
├── ecr_guidance_variables.txt       # ECR variables guidance (used by CD prompt)
├── ecs_guidance_terraform.txt      # ECS Terraform guidance (used by CD prompt)
└── ecs_guidance_variables.txt       # ECS variables guidance (used by CD prompt)
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

### Available Prompts (Active)

1. **repo_scanner** - Analyzes repository structure and identifies technologies

   - Variables: `repo_url`, `branch`, `manifest_context`
   - Used by: orchestrator.py

2. **pipeline_designer** - Designs CI/CD pipeline stages

   - Variables: `repo_analysis`, `repo_structure`
   - Used by: orchestrator.py

3. **security_compliance** - Reviews pipeline for security and compliance

   - Variables: `pipeline_design`, `analysis_context`
   - Used by: orchestrator.py

4. **yaml_generator_ci** - Generates CI (Continuous Integration) workflow YAML

   - Variables: `pipeline_design`, `repo_structure`
   - Used by: orchestrator.py (generates CI workflow separately)
   - **AUTHORITATIVE** for CI workflow generation

5. **yaml_generator_cd** - Generates CD (Continuous Deployment) workflow YAML

   - Variables: `pipeline_design`, `ecr_guidance`, `ecs_guidance`, `repo_structure`, `terraform_working_dir`
   - Used by: orchestrator.py (generates CD workflow separately)
   - **AUTHORITATIVE** for CD workflow generation
   - Includes: OIDC permissions, NPM setup, Terraform setup, AWS CLI formatting, deploy job completeness

6. **pr_manager** - Generates PR description

   - Variables: `repo_url`, `branch`, `pipeline_summary`, `security_summary`, `yaml_section`
   - Used by: orchestrator.py

7. **pr_body_default** - Default PR body template
   - Variables: `timestamp`
   - Used by: orchestrator.py

### Guidance Files (Used by CD Prompt)

- **ecr_guidance_terraform.txt** - ECR configuration when Terraform is used
- **ecr_guidance_variables.txt** - ECR configuration when using GitHub variables
- **ecs_guidance_terraform.txt** - ECS configuration when Terraform is used
- **ecs_guidance_variables.txt** - ECS configuration when using GitHub variables

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

## Prompt Hierarchy and Authoritative Sources

### Workflow Generation

- **CI Workflow**: `yaml_generator_ci.txt` is the authoritative source
  - Contains: Security scanning job definitions, CI trigger configuration
  - Trigger: `pull_request` with `types: [opened, reopened]`
- **CD Workflow**: `yaml_generator_cd.txt` is the authoritative source
  - Contains: Infrastructure, build, and deploy job definitions
  - Contains: OIDC permissions, NPM setup, Terraform setup, AWS CLI formatting
  - Trigger: `pull_request` with `types: [closed]`
  - References: `ecr_guidance_*.txt` and `ecs_guidance_*.txt` for Terraform-specific guidance

### Shared Instructions

- **Security Scanning**: Defined in `yaml_generator_ci.txt` (authoritative) and `pipeline_designer.txt` (design phase)
- **OIDC Permissions**: Defined in `yaml_generator_cd.txt` (authoritative)
- **NPM Setup**: Defined in `yaml_generator_cd.txt` (authoritative)
- **Terraform Setup**: Defined in `yaml_generator_cd.txt` (concise) and guidance files (detailed)
- **Job Sequencing**: Defined in `yaml_generator_cd.txt` (authoritative)
- **AWS CLI Formatting**: Defined in `yaml_generator_cd.txt` (authoritative)

## Example: Updating OIDC Authentication Rules

To update OIDC authentication requirements:

1. Edit `yaml_generator_cd.txt` - Update OIDC permissions section (authoritative source)
2. Edit `security_compliance.txt` - Update security review guidelines if needed
3. No need to modify `orchestrator.py` code

**Note**: Do not edit `yaml_generator_base.txt` as it is obsolete and not used.

## Architecture Change

The orchestrator now generates CI and CD workflows in **separate agent calls** to avoid token limit issues:

1. First call: Generate CI workflow using `yaml_generator_ci.txt`
2. Second call: Generate CD workflow using `yaml_generator_cd.txt`

This ensures each workflow is complete and not truncated.

## Maintaining Consistency and Avoiding Duplicates

### Key Principles

1. **Single Source of Truth**: Each instruction category has one authoritative source
2. **No Duplication**: Do not duplicate instructions across multiple files
3. **Reference, Don't Repeat**: If guidance is needed elsewhere, reference the authoritative source

### When Modifying Instructions

**Before adding new instructions, check:**

- Is this instruction already in an authoritative file?
- Can I reference the existing instruction instead of duplicating it?
- Which file should be the authoritative source for this instruction?

**Authoritative File Mapping:**

- **CI Workflow Instructions** → `yaml_generator_ci.txt`
- **CD Workflow Instructions** → `yaml_generator_cd.txt`
- **Security Scanning Details** → `yaml_generator_ci.txt` (for implementation) or `pipeline_designer.txt` (for design)
- **Terraform-Specific ECR/ECS** → `ecr_guidance_terraform.txt` / `ecs_guidance_terraform.txt`
- **General CD Requirements** → `yaml_generator_cd.txt`

### Common Pitfalls to Avoid

❌ **Don't**: Add OIDC instructions to multiple files
✅ **Do**: Add to `yaml_generator_cd.txt` only (authoritative source)

❌ **Don't**: Duplicate security scanning job definitions
✅ **Do**: Keep in `yaml_generator_ci.txt` (authoritative) and reference from other files

❌ **Don't**: Add job sequencing rules to multiple files
✅ **Do**: Keep in `yaml_generator_cd.txt` (authoritative) with detailed examples

❌ **Don't**: Edit obsolete files (`yaml_generator_base.txt`, `yaml_generator_retry.txt`)
✅ **Do**: Edit the active prompts (`yaml_generator_ci.txt`, `yaml_generator_cd.txt`)

### Verification Checklist

When adding or modifying prompts:

- [ ] Checked if instruction already exists in authoritative file
- [ ] Updated only the authoritative source
- [ ] Did not duplicate instructions across files
- [ ] Updated README.md if adding new prompts or changing hierarchy
- [ ] Verified orchestrator.py uses the correct prompt file
