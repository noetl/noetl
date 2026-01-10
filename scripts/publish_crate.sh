#!/bin/bash
set -e

VERSION=${1:-$(grep '^version' Cargo.toml | head -1 | cut -d'"' -f2)}
CRATE=${2:-noetl-cli}

echo "📦 Publishing ${CRATE} v${VERSION} to crates.io..."

# Check if already logged in
if ! cargo login --help &>/dev/null; then
    echo "❌ Cargo not found. Install Rust first:"
    echo "   curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh"
    exit 1
fi

# Check for API token
if [ ! -f ~/.cargo/credentials.toml ] && [ -z "$CARGO_REGISTRY_TOKEN" ]; then
    echo ""
    echo "🔑 No crates.io credentials found."
    echo ""
    echo "To publish, you need a crates.io API token:"
    echo "  1. Go to https://crates.io/settings/tokens"
    echo "  2. Create a new token with 'publish-update' scope"
    echo "  3. Run: cargo login <your-token>"
    echo ""
    echo "Or set environment variable:"
    echo "  export CARGO_REGISTRY_TOKEN=<your-token>"
    echo ""
    exit 1
fi

# Navigate to crate directory
if [ -d "crates/${CRATE}" ]; then
    cd "crates/${CRATE}"
    echo "📂 Publishing from crates/${CRATE}"
elif [ -f "Cargo.toml" ] && grep -q "name = \"${CRATE}\"" Cargo.toml; then
    echo "📂 Publishing from current directory"
else
    echo "❌ Crate ${CRATE} not found"
    exit 1
fi

# Verify Cargo.toml has required fields
echo "🔍 Verifying package metadata..."
required_fields=("description" "license" "repository")
for field in "${required_fields[@]}"; do
    if ! grep -q "^${field}" Cargo.toml && ! grep -q "${field}.workspace = true" Cargo.toml; then
        echo "❌ Missing required field: ${field}"
        echo "   Add to Cargo.toml or workspace Cargo.toml"
        exit 1
    fi
done

# Check if README exists
if [ ! -f "README.md" ]; then
    echo "⚠️  No README.md found. Crates.io strongly recommends including one."
    read -p "Continue anyway? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# Verify package can be built
echo "🔨 Verifying package builds..."
cargo build --release
if [ $? -ne 0 ]; then
    echo "❌ Build failed. Fix errors before publishing."
    exit 1
fi

# Check for uncommitted changes
if git diff --quiet HEAD -- .; then
    echo "✅ No uncommitted changes"
else
    echo "⚠️  Uncommitted changes detected"
    read -p "Continue with publishing? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# Dry run
echo "🧪 Running dry-run..."
cargo publish --dry-run
if [ $? -ne 0 ]; then
    echo "❌ Dry-run failed. Fix errors before publishing."
    exit 1
fi

# Confirm publication
echo ""
echo "Ready to publish ${CRATE} v${VERSION} to crates.io"
echo ""
read -p "Proceed with publication? (y/n) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "❌ Publication cancelled"
    exit 1
fi

# Publish
echo "🚀 Publishing to crates.io..."
cargo publish

echo ""
echo "✅ Successfully published ${CRATE} v${VERSION}!"
echo ""
echo "Package will be available at:"
echo "  https://crates.io/crates/${CRATE}"
echo ""
echo "Users can install with:"
echo "  cargo install ${CRATE}"
echo ""
echo "Wait a few minutes for crates.io to process the upload."
