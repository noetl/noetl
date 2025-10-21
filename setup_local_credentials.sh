#!/bin/bash
# Setup local credentials from templates
# This helps prevent accidentally committing real credentials

CRED_DIR="tests/fixtures/credentials"

echo "=========================================="
echo "Setting up local credentials from templates"
echo "=========================================="
echo ""

# Create a local copy of sf_test.json for actual use
if [ ! -f "$CRED_DIR/sf_test.local.json" ]; then
    echo "Creating sf_test.local.json (for your actual Snowflake credentials)..."
    cp "$CRED_DIR/sf_test.json" "$CRED_DIR/sf_test.local.json"
    echo "✓ Created: $CRED_DIR/sf_test.local.json"
    echo ""
    echo "IMPORTANT: Edit this file with your real credentials:"
    echo "  $CRED_DIR/sf_test.local.json"
    echo ""
    echo "This file is gitignored and won't be committed."
else
    echo "✓ sf_test.local.json already exists"
fi

echo ""
echo "=========================================="
echo "Setup complete!"
echo "=========================================="
echo ""
echo "Usage:"
echo "1. Edit credential files with .local.json extension"
echo "2. These files are automatically ignored by git"
echo "3. Template files (without .local) stay as placeholders"
echo ""
echo "Example:"
echo "  - tests/fixtures/credentials/sf_test.json (template - committed to git)"
echo "  - tests/fixtures/credentials/sf_test.local.json (your actual creds - gitignored)"
