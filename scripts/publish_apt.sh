#!/bin/bash
set -e

VERSION=${1:-2.5.3}
ARCH=${2:-amd64}
DEB_FILE="build/deb/noetl_${VERSION}-1_${ARCH}.deb"
REPO_DIR="apt-repo"
COMPONENTS="main"
CODENAMES="jammy focal noble"  # Ubuntu 22.04, 20.04, 24.04

if [ ! -f "$DEB_FILE" ]; then
    echo "❌ Package not found: $DEB_FILE"
    echo "Build it first with: ./scripts/build_deb.sh $VERSION"
    exit 1
fi

echo "📦 Publishing NoETL .deb to APT repository..."

# Create repository structure
mkdir -p "$REPO_DIR/dists" "$REPO_DIR/pool/main"

# Copy .deb to pool
cp "$DEB_FILE" "$REPO_DIR/pool/main/"

# Create Packages file for each codename
for CODENAME in $CODENAMES; do
    DIST_DIR="$REPO_DIR/dists/$CODENAME/main/binary-$ARCH"
    mkdir -p "$DIST_DIR"
    
    # Generate Packages file
    cd "$REPO_DIR"
    dpkg-scanpackages --arch "$ARCH" pool/ > "dists/$CODENAME/main/binary-$ARCH/Packages"
    gzip -k -f "dists/$CODENAME/main/binary-$ARCH/Packages"
    
    # Generate Release file for component
    cat > "dists/$CODENAME/main/binary-$ARCH/Release" <<EOF
Archive: $CODENAME
Component: main
Origin: NoETL
Label: NoETL
Architecture: $ARCH
EOF
    
    # Generate Release file for distribution
    cat > "dists/$CODENAME/Release" <<EOF
Origin: NoETL
Label: NoETL APT Repository
Suite: $CODENAME
Codename: $CODENAME
Version: ${VERSION}
Architectures: amd64 arm64
Components: main
Description: NoETL APT Repository for Ubuntu
Date: $(date -Ru)
EOF
    
    # Generate checksums for Release file
    cd "dists/$CODENAME"
    {
        echo "MD5Sum:"
        find . -type f -exec md5sum {} \; | sed 's|./||' | awk '{printf " %s %16d %s\n", $1, $2, $3}'
        echo "SHA1:"
        find . -type f -exec sha1sum {} \; | sed 's|./||' | awk '{printf " %s %16d %s\n", $1, $2, $3}'
        echo "SHA256:"
        find . -type f -exec sha256sum {} \; | sed 's|./||' | awk '{printf " %s %16d %s\n", $1, $2, $3}'
    } >> Release
    
    cd ../../..
done

cd ..

echo ""
echo "✅ APT repository created at: $REPO_DIR"
echo ""
echo "To use this repository locally:"
echo "  echo 'deb [trusted=yes] file://$(pwd)/$REPO_DIR jammy main' | sudo tee /etc/apt/sources.list.d/noetl.list"
echo "  sudo apt-get update"
echo "  sudo apt-get install noetl"
echo ""
echo "To publish via GitHub Pages:"
echo "  1. Create 'apt' branch in noetl/noetl repository"
echo "  2. Copy $REPO_DIR/* to root of 'apt' branch"
echo "  3. Enable GitHub Pages on 'apt' branch"
echo "  4. Users add: deb [trusted=yes] https://noetl.github.io/noetl jammy main"
echo ""
echo "Or host on separate repository:"
echo "  1. Create github.com/noetl/apt repository"
echo "  2. Copy $REPO_DIR/* to root"
echo "  3. Enable GitHub Pages"
echo "  4. Users add: deb [trusted=yes] https://noetl.github.io/apt jammy main"
