---
sidebar_position: 10
---

# Homebrew Release Process

This guide documents the process for publishing NoETL CLI releases via Homebrew tap.

## Overview

NoETL uses a Homebrew tap at [noetl/homebrew-tap](https://github.com/noetl/homebrew-tap) for distribution. The tap formula builds from source using the Cargo workspace structure.

## Prerequisites

- Push access to `noetl/noetl` and `noetl/homebrew-tap` repositories
- Local symlink to tap repo: `ln -s ~/projects/noetl/homebrew-tap homebrew-tap`
- Merged changes to master branch

## Release Steps

### 1. Update Version Numbers

Ensure version is updated in workspace configuration:

```toml
# Cargo.toml (workspace root)
[workspace.package]
version = "2.5.3"
```

All workspace members should reference workspace version:

```toml
# crates/noetlctl/Cargo.toml
[package]
name = "noetl"
version.workspace = true
```

**Note**: The crate is named `noetl` (not `noetl-cli`) for clean cargo install.

### 2. Create Git Tag

Tag the release on the main repository:

```bash
git tag v2.5.3
git push origin v2.5.3
```

### 3. Generate SHA256 and Update Formula

Run the publish script to calculate SHA256 from GitHub tarball:

```bash
./scripts/homebrew_publish.sh 2.5.3
```

This script:
- Downloads tarball from GitHub release tag
- Calculates SHA256 checksum
- Updates `homebrew/noetl.rb` with correct URL and SHA256

### 4. Update Homebrew Tap Repository

Copy updated formula to tap and push:

```bash
cp homebrew/noetl.rb homebrew-tap/Formula/noetl.rb
cd homebrew-tap
git add Formula/noetl.rb
git commit -m "Update noetl to v2.5.3"
git push origin main
cd ..
```

### 5. Test Installation

Test the formula locally before announcing:

```bash
# Uninstall existing version
brew uninstall noetl

# Reinstall from tap
brew install noetl

# Verify version
noetl --version
```

### 6. Update Main Repository

Create PR with updated formula SHA256:

```bash
git checkout -b release/homebrew-v2.5.3
git add homebrew/noetl.rb
git commit -m "Update Homebrew formula SHA256 for v2.5.3"
git push origin release/homebrew-v2.5.3
```

Create and merge PR at: `https://github.com/noetl/noetl/pull/new/release/homebrew-v2.5.3`

## Automated Script Workflow

The `scripts/homebrew_publish.sh` script automates most steps:

```bash
#!/bin/bash
# Usage: ./scripts/homebrew_publish.sh 2.5.3

VERSION=$1
URL="https://github.com/noetl/noetl/archive/refs/tags/v${VERSION}.tar.gz"

# Download and calculate SHA256
SHA256=$(curl -sL "$URL" | shasum -a 256 | cut -d' ' -f1)

# Update formula
sed -i '' "s|url \".*\"|url \"$URL\"|" homebrew/noetl.rb
sed -i '' "s|sha256 \".*\"|sha256 \"$SHA256\"|" homebrew/noetl.rb

echo "✅ Formula updated with SHA256: $SHA256"
```

## Formula Structure

The Homebrew formula is located at `homebrew/noetl.rb`:

```ruby
class Noetl < Formula
  desc "NoETL workflow automation CLI"
  homepage "https://noetl.io"
  url "https://github.com/noetl/noetl/archive/refs/tags/v2.5.3.tar.gz"
  sha256 "ca37a41ed35ef0dd1af7f062dade0440f95029738e472c28d389c3b4f9ccbb74"
  license "MIT"
  head "https://github.com/noetl/noetl.git", branch: "master"

  depends_on "rust" => :build

  def install
    cd "crates/noetlctl" do
      system "cargo", "install", *std_cargo_args
    end
  end

  test do
    assert_match "noetl", shell_output("#{bin}/noetl --version")
    
    # Test simple playbook execution
    (testpath/"hello.yaml").write <<~YAML
      apiVersion: noetl.io/v2
      kind: Playbook
      metadata:
        name: test
      workflow:
        - step: start
          tool:
            kind: shell
            cmds: ["echo 'test'"]
          next: [{step: end}]
        - step: end
    YAML
    
    system bin/"noetl", "run", testpath/"hello.yaml"
  end
end
```

## Key Points

- **Workspace Build**: Formula builds from `crates/noetlctl` subdirectory in workspace
- **Source Distribution**: Installs from GitHub release tarball (not prebuilt binaries)
- **Rust Dependency**: Requires Rust toolchain at build time
- **Version Management**: Workspace version in `Cargo.toml` must match Git tag
- **SHA256 Critical**: Must match exact tarball from GitHub release

## Troubleshooting

### Version mismatch after install

If `noetl --version` shows wrong version after install:

1. Check workspace Cargo.toml has correct version
2. Verify Git tag points to commit with workspace version
3. Delete and recreate tag:
   ```bash
   git tag -d v2.5.3
   git push origin :refs/tags/v2.5.3
   git tag v2.5.3
   git push origin v2.5.3
   ```
4. Regenerate SHA256 and update tap

### SHA256 mismatch error

If Homebrew reports SHA256 mismatch:

1. Recalculate SHA256: `./scripts/homebrew_publish.sh 2.5.3`
2. Update tap repository with new SHA256
3. Clear Homebrew cache: `brew cleanup`

### Build failures

Check Rust version compatibility:
```bash
# Formula specifies Rust as dependency
brew info rust

# Test local build
git clone https://github.com/noetl/noetl.git /tmp/noetl-test
cd /tmp/noetl-test/crates/noetlctl
cargo build --release
```

## Related Documentation

- [Homebrew Installation Guide](../installation/homebrew.md)
- [APT Release Process](./apt-releases.md)
