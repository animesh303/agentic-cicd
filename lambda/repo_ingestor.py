#!/usr/bin/env python3
"""
Repository Ingestor Lambda
Clones repository and extracts manifest files (Dockerfile, package.json, pom.xml, Terraform, CloudFormation, Helm, K8s manifests)
"""
import os
import subprocess
import tempfile
import shutil


def extract_manifest_content(file_path):
    """Extract content from manifest files"""
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            return f.read()
    except Exception:
        return None


def lambda_handler(event, context):
    """
    Event: {
        "repo_url": "https://github.com/owner/repo",
        "branch": "main"
    }
    """
    repo_url = event.get('repo_url') or event.get('repo')
    branch = event.get('branch') or 'main'

    if not repo_url:
        return {'status': 'error', 'message': 'repo_url required'}

    tmpdir = tempfile.mkdtemp()
    manifests = {
        'dockerfiles': [],
        'package_manifests': [],
        'infrastructure': [],
        'kubernetes': [],
        'helm': []
    }

    try:
        # Clone repository
        cmd = ['git', 'clone', '--depth', '1', '--branch', branch, repo_url, tmpdir]
        subprocess.check_call(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        # Walk through repository
        for root, dirs, files in os.walk(tmpdir):
            # Skip .git directory
            dirs[:] = [d for d in dirs if d != '.git']

            for f in files:
                file_path = os.path.join(root, f)
                rel_path = os.path.relpath(file_path, tmpdir)

                # Dockerfiles
                if f.lower().startswith('dockerfile') or f == 'Dockerfile':
                    content = extract_manifest_content(file_path)
                    manifests['dockerfiles'].append({
                        'path': rel_path,
                        'content': content
                    })

                # Package manifests
                elif f in ['package.json', 'requirements.txt', 'pom.xml', 'build.gradle', 'go.mod', 'Cargo.toml']:
                    content = extract_manifest_content(file_path)
                    manifests['package_manifests'].append({
                        'path': rel_path,
                        'type': f,
                        'content': content
                    })

                # Infrastructure as Code
                elif f.endswith('.tf') or f.endswith('.tf.json'):
                    content = extract_manifest_content(file_path)
                    manifests['infrastructure'].append({
                        'path': rel_path,
                        'type': 'terraform',
                        'content': content
                    })
                elif f.endswith('.yaml') or f.endswith('.yml'):
                    content = extract_manifest_content(file_path)
                    # Check for CloudFormation
                    if 'AWSTemplateFormatVersion' in content or 'Resources:' in content:
                        manifests['infrastructure'].append({
                            'path': rel_path,
                            'type': 'cloudformation',
                            'content': content
                        })
                    # Check for Kubernetes
                    elif 'apiVersion' in content and ('kind: Deployment' in content or 'kind: Service' in content):
                        manifests['kubernetes'].append({
                            'path': rel_path,
                            'content': content
                        })
                    # Check for Helm
                    elif f == 'Chart.yaml' or f == 'values.yaml':
                        manifests['helm'].append({
                            'path': rel_path,
                            'content': content
                        })

        result = {
            'status': 'success',
            'repo_url': repo_url,
            'branch': branch,
            'manifests': manifests
        }
        return result

    except Exception as e:
        return {'status': 'error', 'message': str(e)}
    finally:
        try:
            shutil.rmtree(tmpdir)
        except Exception:
            pass

