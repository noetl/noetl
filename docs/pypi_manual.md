# NoETL PyPI Publishing Guide

This guide provides detailed instructions for building and publishing the NoETL package to PyPI.

## Prerequisites

- Python 3.11+ (3.12 recommended)
- `build` package: `pip install build`
- `twine` package: `pip install twine`
- PyPI account with access to the NoETL project
- `.pypirc` file with PyPI credentials or PyPI API token

## Overview

NoETL uses the following tools for packaging and publishing:

- `build`: For building the package
- `twine`: For uploading the package to PyPI
- `hatchling`: As the build backend (specified in `pyproject.toml`)

The process involves:

1. Updating the version number
2. Building the package
3. Testing the package locally
4. Publishing to TestPyPI (optional but recommended)
5. Publishing to PyPI

## Updating the Version

Before building a new release, update the version number in `pyproject.toml`:

```toml
[project]
name = "noetl"
version = "0.1.19"  # Update this version number
```

You can use the provided script to update the version:

```bash
python scripts/update_version.py 0.1.19
```

## Building the Package

NoETL provides a script for building the package:

```bash
./scripts/build_package.sh
```

This script:

1. Cleans the `dist/` directory
2. Builds the package using `python -m build`
3. Verifies the built package

You can also build the package manually:

```bash
# Clean the dist directory
rm -rf dist/

# Build the package
python -m build
```

This will create both source distribution (`.tar.gz`) and wheel (`.whl`) files in the `dist/` directory.

## Testing the Package Locally

Before publishing, test the package locally:

```bash
# Create a virtual environment for testing
python -m venv test_env
source test_env/bin/activate

# Install the package
pip install dist/noetl-*.whl

# Test the package
noetl --version
```

## Publishing to TestPyPI

It's recommended to publish to TestPyPI first to verify the package works correctly:

```bash
# Using the provided script
./scripts/pypi_publish.sh --test 0.1.19

# Or manually
python -m twine upload --repository testpypi dist/*
```

After publishing to TestPyPI, you can install the package from TestPyPI to verify it works:

```bash
pip install --index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ noetl==0.1.19
```

## Publishing to PyPI

Once you've verified the package works correctly on TestPyPI, you can publish to PyPI:

```bash
# Using the provided script
./scripts/pypi_publish.sh 0.1.19

# Or manually
python -m twine upload dist/*
```

## Using the Interactive Publishing Wizard

NoETL provides an interactive publishing wizard that guides you through the process:

```bash
./scripts/interactive_publish.sh
```

This wizard will:

1. Check your environment
2. Update the version number
3. Build the package
4. Verify the package
5. Publish to TestPyPI (optional)
6. Publish to PyPI

## Authentication

There are two ways to authenticate with PyPI:

### 1. Using a `.pypirc` File

Create a `.pypirc` file in your home directory:

```ini
[distutils]
index-servers =
    pypi
    testpypi

[pypi]
username = __token__
password = pypi-your-api-token

[testpypi]
repository = https://test.pypi.org/legacy/
username = __token__
password = pypi-your-test-api-token
```

Replace `pypi-your-api-token` and `pypi-your-test-api-token` with your actual API tokens.

### 2. Using Environment Variables

You can also use environment variables:

```bash
export PYPI_TOKEN=pypi-your-api-token
export TESTPYPI_TOKEN=pypi-your-test-api-token

# Then use the scripts with the environment variables
./scripts/pypi_publish.sh --test 0.1.19
./scripts/pypi_publish.sh 0.1.19
```

## Troubleshooting

### Package Already Exists

If you get an error that the package already exists, it means a package with the same version number has already been published. You need to update the version number in `pyproject.toml` and try again.

### Authentication Errors

If you get authentication errors, check:

1. Your PyPI credentials or API token
2. Your `.pypirc` file or environment variables
3. Your PyPI account permissions for the NoETL project

### Build Errors

If you get build errors, check:

1. Your `pyproject.toml` file
2. Your project structure
3. Your dependencies

## Continuous Integration

NoETL uses GitHub Actions for continuous integration. The workflow is defined in `.github/workflows/publish.yml`. This workflow:

1. Builds the package
2. Runs tests
3. Publishes to PyPI when a new release is created

## Next Steps

- [Development Guide](development.md) - Learn about setting up a development environment
- [Installation Guide](installation.md) - Learn about installing NoETL
- [CLI Usage Guide](cli_usage.md) - Learn how to use the NoETL command-line interface
- [API Usage Guide](api_usage.md) - Learn how to use the NoETL REST API