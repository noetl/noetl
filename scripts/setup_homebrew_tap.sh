#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
TAP_DIR="${HOME}/projects/noetl/homebrew-tap"

echo "Setting up Homebrew tap at: $TAP_DIR"

# Check if tap directory exists
if [ ! -d "$TAP_DIR" ]; then
    echo "Error: Tap directory not found at $TAP_DIR"
    echo "Please clone the repository first:"
    echo "  git clone git@github.com:noetl/homebrew-tap.git ~/projects/noetl/homebrew-tap"
    exit 1
fi

cd "$TAP_DIR"

# Create Formula directory
echo "Creating Formula directory..."
mkdir -p Formula

# Copy formula
echo "Copying formula..."
cp "${REPO_ROOT}/homebrew/noetl.rb" Formula/noetl.rb

# Copy README
echo "Copying README..."
cp "${REPO_ROOT}/homebrew/README.md" README.md

# Check if formula has placeholders
if grep -q "sha256 \"\"" Formula/noetl.rb; then
    echo ""
    echo "⚠️  WARNING: Formula still has empty SHA256 placeholder"
    echo "Run the homebrew_publish.sh script first:"
    echo "  ./scripts/homebrew_publish.sh 2.5.3"
    echo ""
    read -p "Continue anyway? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# Git operations
echo "Adding files to git..."
git add .

echo "Committing..."
git commit -m "Initial formula for noetl CLI v2.5.3

- Add noetl formula with source build support
- Include installation and usage documentation
- Formula installs from crates/noetlcli workspace member"

echo "Pushing to GitHub..."
git push origin main

echo ""
echo "✅ Homebrew tap setup complete!"
echo ""
echo "Users can now install with:"
echo "  brew tap noetl/tap"
echo "  brew install noetl"
echo ""
echo "Test locally with:"
echo "  brew install --build-from-source Formula/noetl.rb"
