#!/bin/bash
# Build script for Lambda functions
# This script packages all Lambda functions into a single deployment package

set -e  # Exit on error

# Get the script directory and project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Configuration
LAMBDA_DIR="$PROJECT_ROOT/lambda"
BUILD_DIR="$PROJECT_ROOT/build/lambda_package"
ZIP_FILE="$PROJECT_ROOT/build/lambda_functions.zip"
BUILD_PARENT="$PROJECT_ROOT/build"

echo "=========================================="
echo "Building Lambda Functions Deployment Package"
echo "=========================================="
echo "Project Root: $PROJECT_ROOT"
echo "Lambda Source: $LAMBDA_DIR"
echo "Build Directory: $BUILD_DIR"
echo "Output ZIP: $ZIP_FILE"
echo ""

# Ensure build directory exists
echo "Creating build directories..."
mkdir -p "$BUILD_PARENT"
mkdir -p "$BUILD_DIR"

# Remove existing zip file if it exists
if [ -f "$ZIP_FILE" ]; then
    echo "Removing existing zip file..."
    rm -f "$ZIP_FILE"
fi

# Clean build directory
echo "Cleaning build directory..."
rm -rf "$BUILD_DIR"/*
mkdir -p "$BUILD_DIR"

# Verify Lambda directory exists
if [ ! -d "$LAMBDA_DIR" ]; then
    echo "Error: Lambda directory not found: $LAMBDA_DIR" >&2
    exit 1
fi

# Copy Lambda function files
echo "Copying Lambda function files..."
if ls "$LAMBDA_DIR"/*.py 1> /dev/null 2>&1; then
    cp "$LAMBDA_DIR"/*.py "$BUILD_DIR/"
    echo "  Copied Python files:"
    ls -1 "$BUILD_DIR"/*.py | xargs -n1 basename | sed 's/^/    - /'
else
    echo "Error: No Python files found in $LAMBDA_DIR" >&2
    exit 1
fi

# Install dependencies if requirements.txt exists
if [ -f "$LAMBDA_DIR/requirements.txt" ]; then
    echo ""
    echo "Installing dependencies from requirements.txt..."
    echo "  Target: Linux (Lambda runtime compatible)"
    
    # Try platform-specific install first (for Lambda Linux runtime)
    if pip install -r "$LAMBDA_DIR/requirements.txt" \
        -t "$BUILD_DIR" \
        --platform manylinux2014_x86_64 \
        --implementation cp \
        --python-version 3.11 \
        --only-binary=:all: \
        --upgrade \
        --quiet \
        --disable-pip-version-check 2>&1; then
        echo "  ✓ Dependencies installed (platform-specific)"
    else
        echo "  Warning: Platform-specific install failed, trying standard install..."
        pip install -r "$LAMBDA_DIR/requirements.txt" \
            -t "$BUILD_DIR" \
            --upgrade \
            --quiet \
            --disable-pip-version-check
        echo "  ✓ Dependencies installed (standard)"
    fi
else
    echo "  No requirements.txt found, skipping dependency installation"
fi

# Ensure zip file's parent directory exists
ZIP_DIR=$(dirname "$ZIP_FILE")
mkdir -p "$ZIP_DIR"

# Create zip file using Python
echo ""
echo "Creating deployment package..."
python3 <<PYTHON_SCRIPT
import os
import zipfile
import sys

build_dir = "$BUILD_DIR"
zip_file = "$ZIP_FILE"

if not os.path.exists(build_dir):
    print(f"Error: Build directory does not exist: {build_dir}", file=sys.stderr)
    sys.exit(1)

try:
    file_count = 0
    with zipfile.ZipFile(zip_file, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(build_dir):
            # Skip __pycache__ directories
            dirs[:] = [d for d in dirs if d != '__pycache__']
            for file in files:
                # Skip .pyc files
                if file.endswith('.pyc'):
                    continue
                file_path = os.path.join(root, file)
                arcname = os.path.relpath(file_path, build_dir)
                zipf.write(file_path, arcname)
                file_count += 1
    
    # Get file size
    file_size = os.path.getsize(zip_file)
    file_size_mb = file_size / (1024 * 1024)
    
    print(f"  ✓ Created zip file: {zip_file}")
    print(f"  ✓ Files packaged: {file_count}")
    print(f"  ✓ Package size: {file_size_mb:.2f} MB")
    
except Exception as e:
    print(f"Error creating zip file: {e}", file=sys.stderr)
    sys.exit(1)
PYTHON_SCRIPT

if [ $? -eq 0 ]; then
    echo ""
    echo "=========================================="
    echo "✓ Build completed successfully!"
    echo "=========================================="
    echo "Deployment package: $ZIP_FILE"
    echo ""
    exit 0
else
    echo ""
    echo "=========================================="
    echo "✗ Build failed!"
    echo "=========================================="
    exit 1
fi

