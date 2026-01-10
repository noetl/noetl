#!/bin/bash
# Publish NoETL to Homebrew tap
# Usage: ./scripts/homebrew_publish.sh <version>

set -e

VERSION=${1:-$(grep '^version = ' Cargo.toml | head -1 | sed 's/version = "\(.*\)"/\1/')}
REPO="noetl/noetl"
FORMULA_PATH="homebrew/noetl.rb"

echo "📦 Publishing NoETL v${VERSION} to Homebrew..."

# Check if tag exists
if ! git rev-parse "v${VERSION}" >/dev/null 2>&1; then
    echo "❌ Tag v${VERSION} does not exist. Create it first:"
    echo "   git tag v${VERSION}"
    echo "   git push origin v${VERSION}"
    exit 1
fi

# Calculate SHA256 for the tarball
echo "🔐 Calculating SHA256..."
TARBALL_URL="https://github.com/${REPO}/archive/refs/tags/v${VERSION}.tar.gz"
SHA256=$(curl -sL "${TARBALL_URL}" | shasum -a 256 | awk '{print $1}')

echo "   URL: ${TARBALL_URL}"
echo "   SHA256: ${SHA256}"

# Update formula
echo "📝 Updating formula..."
sed -i.bak \
    -e "s|url \".*\"|url \"${TARBALL_URL}\"|" \
    -e "s|sha256 \".*\"|sha256 \"${SHA256}\"|" \
    "${FORMULA_PATH}"
rm "${FORMULA_PATH}.bak"

echo "✅ Formula updated: ${FORMULA_PATH}"
echo ""
echo "Next steps:"
echo "1. Test the formula locally:"
echo "   brew install --build-from-source ${FORMULA_PATH}"
echo "   noetl --version"
echo ""
echo "2. Create/update Homebrew tap repository:"
echo "   https://github.com/noetl/homebrew-tap"
echo ""
echo "3. Copy formula to tap:"
echo "   cp ${FORMULA_PATH} /path/to/homebrew-tap/Formula/noetl.rb"
echo "   cd /path/to/homebrew-tap"
echo "   git add Formula/noetl.rb"
echo "   git commit -m 'noetl ${VERSION}'"
echo "   git push"
echo ""
echo "4. Users can then install with:"
echo "   brew tap noetl/tap"
echo "   brew install noetl"
