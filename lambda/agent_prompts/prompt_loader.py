#!/usr/bin/env python3
"""
Prompt Loader Utility
Loads and formats agent prompts from template files.
"""
import os
from pathlib import Path


# Get the directory where this module is located
_PROMPTS_DIR = Path(__file__).parent


def load_prompt(template_name: str) -> str:
    """
    Load a prompt template from file.
    
    Args:
        template_name: Name of the template file (without .txt extension)
        
    Returns:
        The prompt template as a string
        
    Raises:
        FileNotFoundError: If the template file doesn't exist
    """
    template_path = _PROMPTS_DIR / f"{template_name}.txt"
    
    if not template_path.exists():
        raise FileNotFoundError(
            f"Prompt template '{template_name}' not found at {template_path}"
        )
    
    with open(template_path, "r", encoding="utf-8") as f:
        return f.read().strip()


def format_prompt(template_name: str, **kwargs) -> str:
    """
    Load and format a prompt template with provided variables.
    
    Args:
        template_name: Name of the template file (without .txt extension)
        **kwargs: Variables to format into the template
        
    Returns:
        The formatted prompt string
        
    Example:
        prompt = format_prompt("repo_scanner", 
                              repo_url="https://github.com/owner/repo",
                              branch="main",
                              manifest_context="...")
    """
    template = load_prompt(template_name)
    return template.format(**kwargs)


def list_available_prompts() -> list:
    """
    List all available prompt templates.
    
    Returns:
        List of prompt template names (without .txt extension)
    """
    prompts = []
    for file_path in _PROMPTS_DIR.glob("*.txt"):
        prompts.append(file_path.stem)
    return sorted(prompts)

