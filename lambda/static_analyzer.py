#!/usr/bin/env python3
"""
Static Analyzers & Scanners Lambda
Runs deterministic tools to gather facts: dependency manifests, test suites, Dockerfile problems, 
license & vulnerabilities (Semgrep, Trivy, Snyk, OSS scanners)
"""
import json
import os
import subprocess
import tempfile
import shutil
import re

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

def lambda_handler(event, context):
    """
    Event: {
        "repo_url": "https://github.com/owner/repo",
        "branch": "main",
        "analysis_types": ["dockerfile", "dependencies", "tests"]  # optional
    }
    """
    repo_url = event.get('repo_url') or event.get('repo')
    branch = event.get('branch') or 'main'
    analysis_types = event.get('analysis_types', ['dockerfile', 'dependencies', 'tests'])
    
    if not repo_url:
        return {'status': 'error', 'message': 'repo_url required'}

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
        # Clone repository
        cmd = ['git', 'clone', '--depth', '1', '--branch', branch, repo_url, tmpdir]
        subprocess.check_call(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
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
        
        results['status'] = 'success'
        return results
        
    except Exception as e:
        return {'status': 'error', 'message': str(e)}
    finally:
        try:
            shutil.rmtree(tmpdir)
        except Exception:
            pass

