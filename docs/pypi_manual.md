# NoETL PyPI Publishing Guide

This guide provides comprehensive instructions for publishing the NoETL package to PyPI, including the React UI components that are served alongside the FastAPI server.

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Project Structure](#project-structure)
3. [Build Configuration](#build-configuration)
4. [UI Build Process](#ui-build-process)
5. [Package Building](#package-building)
6. [Publishing to PyPI](#publishing-to-pypi)
7. [Verification](#verification)
8. [Automation Scripts](#automation-scripts)
9. [Troubleshooting](#troubleshooting)

## Prerequisites

### Required Tools

1. **Python 3.11+** with pip and venv
2. **Node.js 18+** and npm (for React UI)
3. **PyPI Account** with API token
4. **Build tools**:
   ```bash
   pip install build twine
   ```

### Environment Setup

1. Create a PyPI account at https://pypi.org/account/register/
2. Generate an API token at https://pypi.org/manage/account/token/
3. Configure the token:
   ```bash
   # Create ~/.pypirc file
   cat > ~/.pypirc << EOF
   [distutils]
   index-servers = pypi testpypi

   [pypi]
   username = __token__
   password = pypi-YOUR_API_TOKEN_HERE

   [testpypi]
   repository = https://test.pypi.org/legacy/
   username = __token__
   password = pypi-YOUR_TEST_API_TOKEN_HERE
   EOF
   
   chmod 600 ~/.pypirc
   ```

## Project Structure

The NoETL package includes both Python backend and React UI components:

```
noetl/
├── pyproject.toml          # Package configuration
├── setup.py               # Setuptools configuration
├── MANIFEST.in            # Package manifest
├── README.md              # Package documentation
├── noetl/                 # Python package
│   ├── __init__.py
│   ├── server.py          # FastAPI server
│   └── ...
├── ui/                    # React UI components
│   ├── __init__.py
│   ├── static/            # Built React assets
│   │   ├── css/
│   │   └── js/
│   └── templates/         # HTML templates
└── scripts/               # Build and publish scripts
```

## Build Configuration

### 1. Update pyproject.toml

The `pyproject.toml` file is already configured for PyPI publishing. Key sections:

```toml
[project]
name = "noetl"
version = "0.1.18"
description = "Not Only Extract Transform Load. A framework to build and run data pipelines and workflows."
# ... other configuration
```

### 2. MANIFEST.in Configuration

Ensure all UI assets are included in the package:

```
include README.md
include LICENSE
include CHANGELOG.md
recursive-include noetl *.py
recursive-include ui/static *
recursive-include ui/templates *
include ui/__init__.py
recursive-exclude * __pycache__
recursive-exclude * *.py[co]
```

### 3. Setup.py Integration

The `setup.py` file should include UI assets as package data:

```python
from setuptools import setup, find_packages

setup(
    # ... other configuration
    packages=find_packages(),
    include_package_data=True,
    package_data={
        'ui': ['static/**/*', 'templates/**/*'],
    },
)
```

## UI Build Process

### 1. React UI Development Setup

If you need to modify the React UI, set up the development environment:

```bash
# Navigate to UI source directory (if exists)
cd ui-src/  # or wherever React source is located

# Install dependencies
npm install

# Development server
npm start

# Build for production
npm run build
```

### 2. UI Integration with FastAPI

The UI assets are served by the FastAPI server. Update `noetl/server.py`:

```python
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import os
from pathlib import Path

app = FastAPI()

# Get the UI directory path
ui_dir = Path(__file__).parent.parent / "ui"
static_dir = ui_dir / "static"
templates_dir = ui_dir / "templates"

# Mount static files
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

# Setup templates
if templates_dir.exists():
    templates = Jinja2Templates(directory=str(templates_dir))

@app.get("/ui")
async def serve_ui():
    """Serve the React UI"""
    return templates.TemplateResponse("index.html", {"request": request})
```

## Package Building

### 1. Version Management

Update the version in `pyproject.toml` before building:

```bash
# Use the version update script
./scripts/update_version.py 0.1.19
```

### 2. Clean Previous Builds

```bash
# Clean previous builds
rm -rf dist/ build/ *.egg-info/
```

### 3. Build the Package

```bash
# Build source distribution and wheel
python -m build
```

This creates:
- `dist/noetl-0.1.19.tar.gz` (source distribution)
- `dist/noetl-0.1.19-py3-none-any.whl` (wheel)

## Publishing to PyPI

### 1. Test on TestPyPI First

```bash
# Upload to TestPyPI
python -m twine upload --repository testpypi dist/*

# Test installation from TestPyPI
pip install --index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ noetl
```

### 2. Publish to PyPI

```bash
# Upload to PyPI
python -m twine upload dist/*

# Verify upload
pip install noetl
```

### 3. Automated Publishing

Use the provided script for automated publishing:

```bash
# Publish with version bump
./scripts/publish_to_pypi.sh 0.1.19

# Or use the interactive script
./scripts/interactive_publish.sh
```

## Verification

### 1. Installation Verification

```bash
# Create a new virtual environment
python -m venv test_env
source test_env/bin/activate

# Install from PyPI
pip install noetl

# Test the installation
python -c "import noetl; print(noetl.__version__)"

# Test the server with UI
noetl server --port 8082
# Visit http://localhost:8082/ui to verify UI is working
```

### 2. Package Contents Verification

```bash
# Check package contents
pip show -f noetl

# Verify UI assets are included
python -c "
import noetl
from pathlib import Path
ui_dir = Path(noetl.__file__).parent.parent / 'ui'
print('UI directory exists:', ui_dir.exists())
print('Static files:', list((ui_dir / 'static').glob('**/*')))
"
```

## Automation Scripts

The following scripts automate the publishing process:

1. **`scripts/build_ui.sh`** - Builds the React UI
2. **`scripts/update_version.py`** - Updates package version
3. **`scripts/build_package.sh`** - Builds the Python package
4. **`scripts/publish_to_pypi.sh`** - Publishes to PyPI
5. **`scripts/interactive_publish.sh`** - Interactive publishing workflow

### Usage Examples

```bash
# Full automated release
./scripts/interactive_publish.sh

# Manual step-by-step
./scripts/build_ui.sh
./scripts/update_version.py 0.1.19
./scripts/build_package.sh
./scripts/publish_to_pypi.sh 0.1.19
```

## Troubleshooting

### Common Issues

#### 1. UI Assets Not Included

**Problem**: UI files not found after installation

**Solution**: 
- Verify `MANIFEST.in` includes UI files
- Check `package_data` in `setup.py`
- Rebuild the package

#### 2. Version Conflicts

**Problem**: Version already exists on PyPI

**Solution**:
```bash
# Update version
./scripts/update_version.py 0.1.20
# Rebuild and republish
```

#### 3. Authentication Issues

**Problem**: Upload fails with authentication error

**Solution**:
- Verify PyPI API token
- Check `~/.pypirc` configuration
- Regenerate API token if needed

#### 4. Large Package Size

**Problem**: Package is too large

**Solution**:
- Optimize UI build (remove source maps, minify)
- Exclude unnecessary files in `MANIFEST.in`
- Use `.pypiignore` file

### Debug Commands

```bash
# Check package contents before upload
tar -tzf dist/noetl-*.tar.gz

# Validate package
python -m twine check dist/*

# Verbose upload with debug info
python -m twine upload --verbose dist/*
```

## Best Practices

### 1. Version Management

- Use semantic versioning (MAJOR.MINOR.PATCH)
- Update CHANGELOG.md for each release
- Tag releases in Git

### 2. Testing

- Always test on TestPyPI first
- Verify installation in clean environment
- Test UI functionality after installation

### 3. Documentation

- Keep README.md updated
- Include installation and usage instructions
- Document UI features and endpoints

### 4. Security

- Use API tokens, never passwords
- Rotate tokens regularly
- Use separate tokens for TestPyPI and PyPI

## Continuous Integration

Consider setting up GitHub Actions for automated publishing:

```yaml
# .github/workflows/publish.yml
name: Publish to PyPI

on:
  release:
    types: [published]

jobs:
  publish:
    runs-on: ubuntu-latest
    steps:
    - uses: actions/checkout@v3
    - name: Set up Python
      uses: actions/setup-python@v3
      with:
        python-version: '3.11'
    - name: Build package
      run: |
        pip install build
        python -m build
    - name: Publish to PyPI
      uses: pypa/gh-action-pypi-publish@release/v1
      with:
        password: ${{ secrets.PYPI_API_TOKEN }}
```

## Support

For issues related to PyPI publishing:

1. Check the [PyPI documentation](https://packaging.python.org/)
2. Review the [twine documentation](https://twine.readthedocs.io/)
3. Consult the [setuptools documentation](https://setuptools.pypa.io/)

For NoETL-specific issues, refer to the main documentation or create an issue in the project repository.
