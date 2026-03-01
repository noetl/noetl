#!/bin/bash
set -e

VERSION=${1:-2.5.3}
ARCH=${2:-amd64}
DEB_FILE="build/deb/noetl_${VERSION}-1_${ARCH}.deb"
REPO_DIR="apt-repo"
CODENAMES="jammy focal noble"  # Ubuntu 22.04, 20.04, 24.04

if [ ! -f "$DEB_FILE" ]; then
    echo "❌ Package not found: $DEB_FILE"
    echo "Build it first with: ./scripts/build_deb.sh $VERSION"
    exit 1
fi

echo "📦 Publishing NoETL .deb to APT repository..."

# Create clean repository structure
rm -rf "$REPO_DIR"
mkdir -p "$REPO_DIR/dists" "$REPO_DIR/pool/main"

# Copy all Linux .deb packages from build cache to pool (keeps previous published versions)
for PKG in build/deb/noetl_*.deb; do
    [ -e "$PKG" ] || continue
    PKG_ARCH=$(basename "$PKG" | sed -E 's/^noetl_[^-]+-[0-9]+_([^.]+)\.deb$/\1/')
    case "$PKG_ARCH" in
        amd64|arm64)
            cp "$PKG" "$REPO_DIR/pool/main/"
            ;;
    esac
done

if ! ls "$REPO_DIR"/pool/main/noetl_*.deb >/dev/null 2>&1; then
    echo "❌ No Linux .deb packages found in build/deb/"
    exit 1
fi

# Collect architectures present in repository pool
ARCHES=()
for PKG in "$REPO_DIR"/pool/main/noetl_*.deb; do
    PKG_ARCH=$(basename "$PKG" | sed -E 's/^noetl_[^-]+-[0-9]+_([^.]+)\.deb$/\1/')
    case "$PKG_ARCH" in
        amd64|arm64)
            if [[ ! " ${ARCHES[*]} " =~ " ${PKG_ARCH} " ]]; then
                ARCHES+=("$PKG_ARCH")
            fi
            ;;
    esac
done

if [ "${#ARCHES[@]}" -eq 0 ]; then
    echo "❌ No supported architectures found in pool/main"
    exit 1
fi

ARCH_LINE="${ARCHES[*]}"

# Create Packages file for each codename
for CODENAME in $CODENAMES; do
    cd "$REPO_DIR"

    for REPO_ARCH in "${ARCHES[@]}"; do
        DIST_DIR="dists/$CODENAME/main/binary-$REPO_ARCH"
        mkdir -p "$DIST_DIR"

        # Generate Packages file
        dpkg-scanpackages --multiversion --arch "$REPO_ARCH" pool/ > "dists/$CODENAME/main/binary-$REPO_ARCH/Packages"
        gzip -k -f "dists/$CODENAME/main/binary-$REPO_ARCH/Packages"

        # Generate Release file for component
        cat > "dists/$CODENAME/main/binary-$REPO_ARCH/Release" <<EOF
Archive: $CODENAME
Component: main
Origin: NoETL
Label: NoETL
Architecture: $REPO_ARCH
EOF
    done
    
    # Generate Release file for distribution
    cat > "dists/$CODENAME/Release" <<EOF
Origin: NoETL
Label: NoETL APT Repository
Suite: $CODENAME
Codename: $CODENAME
Version: ${VERSION}
Architectures: ${ARCH_LINE}
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
