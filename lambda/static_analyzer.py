#!/usr/bin/env python3
"""
Static Analyzers & Scanners Lambda
Runs deterministic tools to gather facts: dependency manifests, test suites, Dockerfile problems, 
license & vulnerabilities (Semgrep, Trivy, Snyk, OSS scanners)
"""
import json
import os
import tempfile
import shutil
import re
import zipfile
import requests

def analyze_dockerfile(dockerfile_path):
    """Analyze Dockerfile for best practices and issues"""
    issues = []
    best_practices = []
    
    try:
        with open(dockerfile_path, 'r') as f:
            content = f.read()
            lines = content.split('\n')
            
            # Check for common issues
            for i, line in enumerate(lines, 1):
                line_upper = line.upper().strip()
                
                # Check for root user
                if 'USER root' in line_upper and 'FROM' not in line_upper:
                    issues.append({
                        'line': i,
                        'type': 'security',
                        'message': 'Running as root user',
                        'severity': 'medium'
                    })
                
                # Check for exposed secrets
                if any(keyword in line_upper for keyword in ['PASSWORD', 'SECRET', 'API_KEY', 'TOKEN']):
                    if '=' in line and not line.strip().startswith('#'):
                        issues.append({
                            'line': i,
                            'type': 'security',
                            'message': 'Potential secret exposure',
                            'severity': 'high'
                        })
                
                # Check for latest tag
                if 'FROM' in line_upper and ':latest' in line_upper:
                    issues.append({
                        'line': i,
                        'type': 'best_practice',
                        'message': 'Using :latest tag is not recommended',
                        'severity': 'low'
                    })
            
            # Check for multi-stage builds
            if content.count('FROM') > 1:
                best_practices.append('Uses multi-stage build')
            else:
                issues.append({
                    'type': 'best_practice',
                    'message': 'Consider using multi-stage build',
                    'severity': 'low'
                })
    
    except Exception as e:
        return {'error': str(e)}
    
    return {
        'issues': issues,
        'best_practices': best_practices
    }

def analyze_dependencies(manifest_path, manifest_type):
    """Analyze dependency manifest files"""
    dependencies = []
    test_frameworks = []
    
    try:
        with open(manifest_path, 'r') as f:
            content = f.read()
            
            if manifest_type == 'package.json':
                import json as json_lib
                data = json_lib.loads(content)
                deps = data.get('dependencies', {})
                dev_deps = data.get('devDependencies', {})
                
                dependencies.extend(list(deps.keys()))
                
                # Detect test frameworks
                if 'jest' in dev_deps or 'jest' in deps:
                    test_frameworks.append('jest')
                if 'mocha' in dev_deps or 'mocha' in deps:
                    test_frameworks.append('mocha')
                if 'cypress' in dev_deps:
                    test_frameworks.append('cypress')
            
            elif manifest_type == 'requirements.txt':
                for line in content.split('\n'):
                    line = line.strip()
                    if line and not line.startswith('#'):
                        pkg = line.split('==')[0].split('>=')[0].split('<=')[0].strip()
                        dependencies.append(pkg)
                        
                        if 'pytest' in pkg.lower():
                            test_frameworks.append('pytest')
                        if 'unittest' in pkg.lower():
                            test_frameworks.append('unittest')
            
            elif manifest_type == 'pom.xml':
                # Simple XML parsing for Maven
                deps = re.findall(r'<artifactId>([^<]+)</artifactId>', content)
                dependencies.extend(deps)
                
                if 'junit' in content.lower():
                    test_frameworks.append('junit')
                if 'testng' in content.lower():
                    test_frameworks.append('testng')
    
    except Exception as e:
        return {'error': str(e)}
    
    return {
        'dependencies': dependencies,
        'test_frameworks': list(set(test_frameworks))
    }

def analyze_terraform_ecr(tmpdir):
    """
    Analyze Terraform files to detect ECR repositories and related resources.
    Returns ECR registry, repository name, and output references if found.
    """
    ecr_resources = []
    ecr_outputs = []
    
    try:
        # Find all Terraform files
        terraform_files = []
        for root, dirs, files in os.walk(tmpdir):
            for f in files:
                if f.endswith('.tf') or f.endswith('.tf.json'):
                    terraform_files.append(os.path.join(root, f))
        
        for tf_file in terraform_files:
            try:
                with open(tf_file, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                    
                    # Look for ECR repository resources
                    # Pattern: resource "aws_ecr_repository" "name" { ... }
                    ecr_pattern = r'resource\s+"aws_ecr_repository"\s+"([^"]+)"\s*\{[^}]*name\s*=\s*["\']([^"\']+)["\']'
                    matches = re.finditer(ecr_pattern, content, re.MULTILINE | re.DOTALL)
                    
                    for match in matches:
                        resource_name = match.group(1)
                        repo_name = match.group(2)
                        ecr_resources.append({
                            'resource_name': resource_name,
                            'repository_name': repo_name,
                            'file': os.path.relpath(tf_file, tmpdir)
                        })
                    
                    # Look for ECR outputs
                    # Pattern: output "ecr_registry" { value = ... }
                    # Pattern: output "ecr_repository" { value = ... }
                    output_pattern = r'output\s+"([^"]+)"\s*\{[^}]*value\s*=\s*([^}]+)\}'
                    output_matches = re.finditer(output_pattern, content, re.MULTILINE | re.DOTALL)
                    
                    for match in output_matches:
                        output_name = match.group(1).lower()
                        output_value = match.group(2).strip()
                        
                        # Check if this is an ECR-related output
                        if 'ecr' in output_name or 'registry' in output_name or 'repository' in output_name:
                            # Try to extract the actual value or reference
                            value_ref = None
                            if 'aws_ecr_repository' in output_value:
                                # Extract resource reference like aws_ecr_repository.example.repository_url
                                ref_match = re.search(r'aws_ecr_repository\.([^.]+)\.(repository_url|repository_name)', output_value)
                                if ref_match:
                                    value_ref = f"aws_ecr_repository.{ref_match.group(1)}.{ref_match.group(2)}"
                            
                            ecr_outputs.append({
                                'output_name': match.group(1),
                                'output_value': output_value,
                                'value_reference': value_ref,
                                'file': os.path.relpath(tf_file, tmpdir)
                            })
                    
                    # Look for data source references to ECR
                    # Pattern: data "aws_caller_identity" "current" {} (for registry)
                    if 'data "aws_caller_identity"' in content:
                        # Registry can be constructed from account ID and region
                        ecr_outputs.append({
                            'output_name': 'ecr_registry_derived',
                            'output_value': 'data.aws_caller_identity.current.account_id',
                            'value_reference': 'Derived from AWS account ID',
                            'file': os.path.relpath(tf_file, tmpdir),
                            'note': 'ECR registry can be derived from account ID and region'
                        })
            except Exception as e:
                print(f"Error analyzing Terraform file {tf_file}: {e}")
                continue
        
        return {
            'ecr_resources': ecr_resources,
            'ecr_outputs': ecr_outputs,
            'has_ecr': len(ecr_resources) > 0 or len(ecr_outputs) > 0
        }
    except Exception as e:
        print(f"Error in analyze_terraform_ecr: {e}")
        return {
            'ecr_resources': [],
            'ecr_outputs': [],
            'has_ecr': False,
            'error': str(e)
        }

def analyze_terraform_ecs(tmpdir):
    """
    Analyze Terraform files to detect ECS clusters and services.
    Returns ECS cluster name, service name, and output references if found.
    """
    ecs_resources = []
    ecs_outputs = []
    
    try:
        # Find all Terraform files
        terraform_files = []
        for root, dirs, files in os.walk(tmpdir):
            for f in files:
                if f.endswith('.tf') or f.endswith('.tf.json'):
                    terraform_files.append(os.path.join(root, f))
        
        for tf_file in terraform_files:
            try:
                with open(tf_file, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                    
                    # Look for ECS cluster resources
                    # Pattern: resource "aws_ecs_cluster" "name" { ... }
                    cluster_pattern = r'resource\s+"aws_ecs_cluster"\s+"([^"]+)"\s*\{[^}]*name\s*=\s*["\']([^"\']+)["\']'
                    cluster_matches = re.finditer(cluster_pattern, content, re.MULTILINE | re.DOTALL)
                    
                    for match in cluster_matches:
                        resource_name = match.group(1)
                        cluster_name = match.group(2)
                        ecs_resources.append({
                            'resource_type': 'cluster',
                            'resource_name': resource_name,
                            'name': cluster_name,
                            'file': os.path.relpath(tf_file, tmpdir)
                        })
                    
                    # Look for ECS service resources
                    # Pattern: resource "aws_ecs_service" "name" { ... cluster = ... name = ... }
                    service_pattern = r'resource\s+"aws_ecs_service"\s+"([^"]+)"\s*\{[^}]*cluster\s*=\s*([^,\n}]+)[^}]*name\s*=\s*["\']([^"\']+)["\']'
                    service_matches = re.finditer(service_pattern, content, re.MULTILINE | re.DOTALL)
                    
                    for match in service_matches:
                        resource_name = match.group(1)
                        cluster_ref = match.group(2).strip()
                        service_name = match.group(3)
                        ecs_resources.append({
                            'resource_type': 'service',
                            'resource_name': resource_name,
                            'name': service_name,
                            'cluster_reference': cluster_ref,
                            'file': os.path.relpath(tf_file, tmpdir)
                        })
                    
                    # Look for ECS outputs
                    # Pattern: output "ecs_cluster" { value = ... }
                    # Pattern: output "ecs_service" { value = ... }
                    output_pattern = r'output\s+"([^"]+)"\s*\{[^}]*value\s*=\s*([^}]+)\}'
                    output_matches = re.finditer(output_pattern, content, re.MULTILINE | re.DOTALL)
                    
                    for match in output_matches:
                        output_name = match.group(1).lower()
                        output_value = match.group(2).strip()
                        
                        # Check if this is an ECS-related output
                        if 'ecs' in output_name and ('cluster' in output_name or 'service' in output_name):
                            # Try to extract the actual value or reference
                            value_ref = None
                            if 'aws_ecs_cluster' in output_value:
                                # Extract resource reference like aws_ecs_cluster.example.name
                                ref_match = re.search(r'aws_ecs_cluster\.([^.]+)\.(name|id|arn)', output_value)
                                if ref_match:
                                    value_ref = f"aws_ecs_cluster.{ref_match.group(1)}.{ref_match.group(2)}"
                            elif 'aws_ecs_service' in output_value:
                                # Extract resource reference like aws_ecs_service.example.name
                                ref_match = re.search(r'aws_ecs_service\.([^.]+)\.(name|id)', output_value)
                                if ref_match:
                                    value_ref = f"aws_ecs_service.{ref_match.group(1)}.{ref_match.group(2)}"
                            
                            ecs_outputs.append({
                                'output_name': match.group(1),
                                'output_value': output_value,
                                'value_reference': value_ref,
                                'file': os.path.relpath(tf_file, tmpdir)
                            })
            except Exception as e:
                print(f"Error analyzing Terraform file {tf_file}: {e}")
                continue
        
        return {
            'ecs_resources': ecs_resources,
            'ecs_outputs': ecs_outputs,
            'has_ecs': len(ecs_resources) > 0 or len(ecs_outputs) > 0
        }
    except Exception as e:
        print(f"Error in analyze_terraform_ecs: {e}")
        return {
            'ecs_resources': [],
            'ecs_outputs': [],
            'has_ecs': False,
            'error': str(e)
        }

def detect_test_files(repo_dir):
    """Detect test files and test directories"""
    test_files = []
    test_dirs = []
    
    for root, dirs, files in os.walk(repo_dir):
        # Skip hidden and build directories
        dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ['node_modules', 'target', 'build', '__pycache__']]
        
        # Check directory names
        dir_name = os.path.basename(root)
        if any(keyword in dir_name.lower() for keyword in ['test', 'spec', '__tests__']):
            test_dirs.append(os.path.relpath(root, repo_dir))
        
        # Check file names
        for f in files:
            if any(keyword in f.lower() for keyword in ['test', 'spec', '__test__']):
                test_files.append(os.path.relpath(os.path.join(root, f), repo_dir))
    
    return {
        'test_files': test_files,
        'test_directories': test_dirs
    }

def download_repo_as_zip(repo_url, branch, tmpdir):
    """
    Download a GitHub repository as a ZIP file and extract it.
    Supports both https://github.com/owner/repo and github.com/owner/repo formats.
    This avoids requiring git in the Lambda runtime.
    """
    try:
        # Parse GitHub URL
        original_url = repo_url
        if repo_url.startswith("https://"):
            repo_url = repo_url.replace("https://", "")
        elif repo_url.startswith("http://"):
            repo_url = repo_url.replace("http://", "")

        if repo_url.startswith("github.com/"):
            repo_path = repo_url.replace("github.com/", "")
        elif "/" in repo_url:
            repo_path = repo_url
        else:
            raise ValueError(f"Invalid repository URL format: {original_url}")

        # Remove .git suffix if present
        if repo_path.endswith(".git"):
            repo_path = repo_path[:-4]

        # Split into owner and repo
        parts = repo_path.split("/")
        if len(parts) != 2:
            raise ValueError(
                f"Invalid repository path format: {repo_path}. Expected 'owner/repo'"
            )

        owner, repo = parts[0], parts[1]

        # Use direct download URL (more reliable than API endpoint)
        # Format: https://github.com/{owner}/{repo}/archive/refs/heads/{branch}.zip
        branches_to_try = [branch]

        # Add fallback branches if not already in the list
        if branch.lower() != "main":
            branches_to_try.append("main")
        if branch.lower() != "master":
            branches_to_try.append("master")

        response = None
        zip_url = None

        # Try each branch until one works
        for try_branch in branches_to_try:
            zip_url = (
                f"https://github.com/{owner}/{repo}/archive/refs/heads/{try_branch}.zip"
            )
            print(f"Trying to download: {owner}/{repo} (branch: {try_branch})")
            print(f"URL: {zip_url}")

            response = requests.get(
                zip_url, stream=True, timeout=60, allow_redirects=True
            )

            if response.status_code == 200:
                print(f"✓ Successfully found branch: {try_branch}")
                break
            elif response.status_code == 404:
                print(f"✗ Branch '{try_branch}' not found")
                if try_branch != branches_to_try[-1]:  # Not the last one
                    print("Trying next branch...")
                continue
            else:
                # Some other error, break and handle below
                break

        # Check for errors and provide helpful messages
        if response is None or response.status_code != 200:
            if response is None:
                error_msg = f"Failed to download repository {owner}/{repo}"
            elif response.status_code == 404:
                error_msg = (
                    f"Repository {owner}/{repo} not found or none of the branches exist"
                )
                # Try to get more info from GitHub API
                try:
                    api_url = f"https://api.github.com/repos/{owner}/{repo}"
                    api_response = requests.get(api_url, timeout=10)
                    if api_response.status_code == 404:
                        error_msg = f"Repository {owner}/{repo} not found. It may be private or not exist."
                    elif api_response.status_code == 403:
                        error_msg = f"Repository {owner}/{repo} may be private. Authentication required."
                    elif api_response.status_code == 200:
                        # Repo exists, so branches are wrong
                        repo_data = api_response.json()
                        default_branch = repo_data.get("default_branch", "main")
                        error_msg = f"None of the tried branches exist. Repository exists with default branch: {default_branch}. Tried: {', '.join(branches_to_try)}"
                except Exception as e:
                    print(f"Could not get repository info: {e}")
            else:
                # Other HTTP error
                try:
                    response.raise_for_status()
                except Exception as e:
                    error_msg = f"HTTP error downloading repository: {str(e)}"

            raise Exception(error_msg)

        # Save to temporary zip file
        zip_path = os.path.join(tmpdir, "repo.zip")
        with open(zip_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)

        # Extract zip file
        extract_dir = os.path.join(tmpdir, "extracted")
        os.makedirs(extract_dir, exist_ok=True)

        with zipfile.ZipFile(zip_path, "r") as zip_ref:
            zip_ref.extractall(extract_dir)

        # Find the actual repo directory
        # GitHub archive format: {repo}-{branch} or {repo}-{hash}
        extracted_dirs = [
            d
            for d in os.listdir(extract_dir)
            if os.path.isdir(os.path.join(extract_dir, d))
        ]
        if not extracted_dirs:
            raise Exception("No directory found in extracted zip file")

        # Use the first (and typically only) directory
        actual_repo_dir = os.path.join(extract_dir, extracted_dirs[0])
        print(f"Extracted repository directory: {extracted_dirs[0]}")
        # Move contents to tmpdir root
        for item in os.listdir(actual_repo_dir):
            src = os.path.join(actual_repo_dir, item)
            dst = os.path.join(tmpdir, item)
            if os.path.exists(dst):
                if os.path.isdir(dst):
                    shutil.rmtree(dst)
                else:
                    os.remove(dst)
            shutil.move(src, dst)

        # Clean up
        if os.path.exists(zip_path):
            os.remove(zip_path)
        shutil.rmtree(extract_dir, ignore_errors=True)

        return tmpdir

    except Exception as e:
        raise Exception(f"Failed to download repository: {str(e)}")

def lambda_handler(event, context):
    """
    Handle both direct invocation and Bedrock agent invocation formats.
    
    Direct invocation:
    {
        "repo_url": "https://github.com/owner/repo",
        "branch": "main",
        "analysis_types": ["dockerfile", "dependencies", "tests"]
    }
    
    Bedrock agent invocation (actual format):
    {
        "messageVersion": "1.0",
        "actionGroup": "...",
        "apiPath": "/invoke",
        "httpMethod": "POST",
        "requestBody": {
            "content": {
                "application/json": {
                    "properties": [
                        {"name": "repo_url", "value": "..."},
                        {"name": "branch", "value": "main"},
                        {"name": "analysis_types", "value": [...]}
                    ]
                }
            }
        }
    }
    """
    # Initialize variables for Bedrock format
    action_group = None
    api_path = None
    http_method = None
    
    # Handle Bedrock agent invocation format
    if "messageVersion" in event and "actionGroup" in event:
        # Extract parameters from requestBody.properties array
        request_body = event.get("requestBody", {})
        content = request_body.get("content", {})
        json_content = content.get("application/json", {})
        properties = json_content.get("properties", [])
        
        # Convert properties array to dict
        body_data = {}
        for prop in properties:
            name = prop.get("name")
            value = prop.get("value")
            if name and value is not None:
                body_data[name] = value
        
        repo_url = body_data.get("repo_url") or body_data.get("repo")
        branch = body_data.get("branch", "main")
        analysis_types = body_data.get("analysis_types", ["dockerfile", "dependencies", "tests"])
        
        # Handle array format - if analysis_types is a string, try to parse it
        if isinstance(analysis_types, str):
            try:
                analysis_types = json.loads(analysis_types)
            except:
                # If it's a comma-separated string, split it
                analysis_types = [t.strip() for t in analysis_types.split(",")]
        
        action_group = event.get("actionGroup", "unknown")
        api_path = event.get("apiPath", "/invoke")
        http_method = event.get("httpMethod", "POST")
    elif "actionGroupInvocationInput" in event:
        # Alternative Bedrock format
        action_input = event["actionGroupInvocationInput"]
        request_body = (
            action_input.get("requestBody", {})
            .get("content", {})
            .get("application/json", {})
        )
        body_str = request_body.get("body", "{}")
        
        try:
            body_data = json.loads(body_str) if isinstance(body_str, str) else body_str
            repo_url = body_data.get("repo_url") or body_data.get("repo")
            branch = body_data.get("branch", "main")
            analysis_types = body_data.get("analysis_types", ["dockerfile", "dependencies", "tests"])
        except Exception as e:
            error_response = {
                "messageVersion": "1.0",
                "response": {
                    "actionGroup": action_input.get("actionGroupName", "unknown"),
                    "apiPath": action_input.get("apiPath", "/invoke"),
                    "httpMethod": action_input.get("httpMethod", "POST"),
                    "httpStatusCode": 400,
                    "responseBody": {
                        "application/json": {
                            "body": json.dumps(
                                {
                                    "status": "error",
                                    "message": f"Invalid request body: {str(e)}",
                                }
                            )
                        },
                    },
                },
            }
            return error_response
        
        action_group = action_input.get("actionGroupName", "unknown")
        api_path = action_input.get("apiPath", "/invoke")
        http_method = action_input.get("httpMethod", "POST")
    else:
        # Handle direct invocation format
        repo_url = event.get('repo_url') or event.get('repo')
        branch = event.get('branch', 'main')
        analysis_types = event.get('analysis_types', ['dockerfile', 'dependencies', 'tests'])
    
    if not repo_url:
        error_response = {'status': 'error', 'message': 'repo_url required'}
        # Return in Bedrock format if invoked by agent
        if action_group:
            return {
                "messageVersion": "1.0",
                "response": {
                    "actionGroup": action_group,
                    "apiPath": api_path or "/invoke",
                    "httpMethod": http_method or "POST",
                    "httpStatusCode": 400,
                    "responseBody": {
                        "application/json": {"body": json.dumps(error_response)}
                    },
                },
            }
        return error_response

    tmpdir = tempfile.mkdtemp()
    results = {
        'repo_url': repo_url,
        'branch': branch,
        'dockerfile_analysis': [],
        'dependency_analysis': [],
        'test_analysis': {},
        'vulnerability_scan': {'status': 'not_implemented', 'note': 'Requires Trivy/Snyk integration'}
    }
    
    try:
        # Download repository as ZIP (no git required)
        print(f"Downloading repository: {repo_url} (branch: {branch})")
        download_repo_as_zip(repo_url, branch, tmpdir)
        print(f"Repository downloaded successfully to: {tmpdir}")
        
        # Analyze Dockerfiles
        if 'dockerfile' in analysis_types:
            for root, dirs, files in os.walk(tmpdir):
                for f in files:
                    if f.lower().startswith('dockerfile') or f == 'Dockerfile':
                        dockerfile_path = os.path.join(root, f)
                        analysis = analyze_dockerfile(dockerfile_path)
                        analysis['path'] = os.path.relpath(dockerfile_path, tmpdir)
                        results['dockerfile_analysis'].append(analysis)
        
        # Analyze dependencies
        if 'dependencies' in analysis_types:
            for root, dirs, files in os.walk(tmpdir):
                for f in files:
                    if f in ['package.json', 'requirements.txt', 'pom.xml']:
                        manifest_path = os.path.join(root, f)
                        analysis = analyze_dependencies(manifest_path, f)
                        analysis['manifest_path'] = os.path.relpath(manifest_path, tmpdir)
                        analysis['manifest_type'] = f
                        results['dependency_analysis'].append(analysis)
        
        # Detect test files
        if 'tests' in analysis_types:
            results['test_analysis'] = detect_test_files(tmpdir)
        
        # Analyze Terraform for ECR resources
        if 'terraform' in analysis_types or 'infrastructure' in analysis_types:
            # Analyze both ECR and ECS resources
            ecr_analysis = analyze_terraform_ecr(tmpdir)
            ecs_analysis = analyze_terraform_ecs(tmpdir)
            results['terraform_analysis'] = {
                **ecr_analysis,
                **ecs_analysis
            }
        
        results['status'] = 'success'
        
        # Return in Bedrock format if invoked by agent
        if action_group:
            return {
                "messageVersion": "1.0",
                "response": {
                    "actionGroup": action_group,
                    "apiPath": api_path or "/invoke",
                    "httpMethod": http_method or "POST",
                    "httpStatusCode": 200,
                    "responseBody": {
                        "application/json": {"body": json.dumps(results)}
                    },
                },
            }
        
        return results
        
    except Exception as e:
        error_message = str(e)
        print(f"Error in static_analyzer: {error_message}")
        import traceback
        print(f"Traceback: {traceback.format_exc()}")
        
        error_result = {'status': 'error', 'message': error_message}
        
        # Return in Bedrock format if invoked by agent
        if action_group:
            return {
                "messageVersion": "1.0",
                "response": {
                    "actionGroup": action_group,
                    "apiPath": api_path or "/invoke",
                    "httpMethod": http_method or "POST",
                    "httpStatusCode": 500,
                    "responseBody": {
                        "application/json": {"body": json.dumps(error_result)}
                    },
                },
            }
        
        return error_result
    finally:
        try:
            shutil.rmtree(tmpdir)
        except Exception:
            pass

