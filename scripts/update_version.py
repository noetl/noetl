#!/usr/bin/env python3
"""
Version Update Script for NoETL
"""

import argparse
import re
import sys
from pathlib import Path
from typing import Optional

class Colors:
    RED = '\033[0;31m'
    GREEN = '\033[0;32m'
    YELLOW = '\033[1;33m'
    BLUE = '\033[0;34m'
    NC = '\033[0m'

def print_colored(message: str, color: str = Colors.NC):
    print(f"{color}{message}{Colors.NC}")

def get_current_version(pyproject_path: Path) -> Optional[str]:
    try:
        content = pyproject_path.read_text()
        match = re.search(r'version\s*=\s*["\']([^"\']+)["\']', content)
        return match.group(1) if match else None
    except FileNotFoundError:
        print_colored(f"pyproject.toml not found at {pyproject_path}", Colors.RED)
        return None

def validate_version(version: str) -> bool:
    pattern = r'^\d+\.\d+\.\d+(?:-[a-zA-Z0-9]+(?:\.[a-zA-Z0-9]+)*)?(?:\+[a-zA-Z0-9]+(?:\.[a-zA-Z0-9]+)*)?$'
    return bool(re.match(pattern, version))

def increment_version(current_version: str, increment_type: str) -> str:
    parts = current_version.split('.')
    if len(parts) < 3:
        raise ValueError(f"Invalid version format: {current_version}")

    major, minor, patch = int(parts[0]), int(parts[1]), int(parts[2])

    if increment_type == 'major':
        major += 1
        minor = 0
        patch = 0
    elif increment_type == 'minor':
        minor += 1
        patch = 0
    elif increment_type == 'patch':
        patch += 1
    else:
        raise ValueError(f"Invalid increment type: {increment_type}")

    return f"{major}.{minor}.{patch}"

def update_pyproject_toml(pyproject_path: Path, new_version: str) -> bool:
    try:
        content = pyproject_path.read_text()
        updated_content = re.sub(
            r'version\s*=\s*["\'][^"\']+["\']',
            f'version = "{new_version}"',
            content
        )
        pyproject_path.write_text(updated_content)
        return True
    except Exception as e:
        print_colored(f"Failed to update pyproject.toml: {e}", Colors.RED)
        return False

def update_init_file(init_path: Path, new_version: str) -> bool:
    if not init_path.exists():
        return True

    try:
        content = init_path.read_text()

        if '__version__' in content:
            updated_content = re.sub(
                r'__version__\s*=\s*["\'][^"\']+["\']',
                f'__version__ = "{new_version}"',
                content
            )
        else:
            lines = content.split('\n')
            insert_index = 0
            for i, line in enumerate(lines):
                if line.strip().startswith('"""') and '"""' in line[3:]:
                    insert_index = i + 1
                    break
                elif line.strip().startswith('"""'):
                    for j in range(i + 1, len(lines)):
                        if '"""' in lines[j]:
                            insert_index = j + 1
                            break
                    break

            lines.insert(insert_index, f'__version__ = "{new_version}"')
            updated_content = '\n'.join(lines)

        init_path.write_text(updated_content)
        return True
    except Exception as e:
        print_colored(f"Failed to update __init__.py: {e}", Colors.RED)
        return False

def update_changelog(changelog_path: Path, new_version: str, current_version: str) -> bool:
    if not changelog_path.exists():
        print_colored("CHANGELOG.md not found, skipping changelog update", Colors.YELLOW)
        return True

    try:
        content = changelog_path.read_text()
        from datetime import datetime
        date_str = datetime.now().strftime("%Y-%m-%d")

        new_entry = f"""## [{new_version}] - {date_str}

### Added
- Version bump from {current_version} to {new_version}

### Changed
- 

### Fixed
- 

"""
        lines = content.split('\n')
        if lines and lines[0].startswith('#'):
            lines.insert(2, new_entry)
        else:
            lines.insert(0, new_entry)

        changelog_path.write_text('\n'.join(lines))
        return True
    except Exception as e:
        print_colored(f"Failed to update CHANGELOG.md: {e}", Colors.RED)
        return False

def main():
    parser = argparse.ArgumentParser(description="Update NoETL package version")
    parser.add_argument(
        "version",
        nargs="?",
        help="New version number (e.g., 1.2.3) or increment type (major, minor, patch)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be changed without making changes"
    )
    parser.add_argument(
        "--no-changelog",
        action="store_true",
        help="Skip updating CHANGELOG.md"
    )

    args = parser.parse_args()

    script_dir = Path(__file__).parent
    project_root = script_dir.parent

    pyproject_path = project_root / "pyproject.toml"
    init_path = project_root / "noetl" / "__init__.py"
    changelog_path = project_root / "CHANGELOG.md"

    print_colored("NoETL Version Update Tool", Colors.BLUE)
    print_colored(f"Project root: {project_root}", Colors.BLUE)

    # Get current version
    current_version = get_current_version(pyproject_path)
    if not current_version:
        print_colored("Could not determine current version", Colors.RED)
        sys.exit(1)

    print_colored(f"Current version: {current_version}", Colors.BLUE)

    # Determine new version
    if not args.version:
        print_colored("Please specify a new version or increment type:", Colors.YELLOW)
        print("  python update_version.py 1.2.3")
        print("  python update_version.py patch")
        print("  python update_version.py minor")
        print("  python update_version.py major")
        sys.exit(1)

    if args.version in ['major', 'minor', 'patch']:
        new_version = increment_version(current_version, args.version)
        print_colored(f"Auto-incrementing {args.version}: {current_version} → {new_version}", Colors.BLUE)
    else:
        new_version = args.version
        if not validate_version(new_version):
            print_colored(f"Invalid version format: {new_version}", Colors.RED)
            print("Version must follow semantic versioning (e.g., 1.2.3)")
            sys.exit(1)

    print_colored(f"New version: {new_version}", Colors.GREEN)

    if args.dry_run:
        print_colored("DRY RUN - No changes will be made", Colors.YELLOW)
        print(f"Would update pyproject.toml: {current_version} → {new_version}")
        if init_path.exists():
            print(f"Would update {init_path}")
        if not args.no_changelog and changelog_path.exists():
            print(f"Would update {changelog_path}")
        sys.exit(0)

    response = input(f"Update version from {current_version} to {new_version}? (y/N): ")
    if response.lower() not in ['y', 'yes']:
        print_colored("Version update cancelled", Colors.YELLOW)
        sys.exit(0)

    success = True

    print_colored("Updating pyproject.toml...", Colors.BLUE)
    if not update_pyproject_toml(pyproject_path, new_version):
        success = False
    else:
        print_colored("Updated pyproject.toml", Colors.GREEN)

    print_colored("Updating __init__.py...", Colors.BLUE)
    if not update_init_file(init_path, new_version):
        success = False
    else:
        print_colored("Updated __init__.py", Colors.GREEN)

    if not args.no_changelog:
        print_colored("Updating CHANGELOG.md...", Colors.BLUE)
        if not update_changelog(changelog_path, new_version, current_version):
            success = False
        else:
            print_colored("Updated CHANGELOG.md", Colors.GREEN)

    if success:
        print_colored(f"Successfully updated version to {new_version}!", Colors.GREEN)
        print_colored("Next steps:", Colors.BLUE)
        print("  1. Review the changes")
        print("  2. Update CHANGELOG.md with specific changes")
        print("  3. Commit the version bump")
        print("  4. Build and publish the package")
    else:
        print_colored("Some updates failed. Please check the errors above.", Colors.RED)
        sys.exit(1)

if __name__ == "__main__":
    main()
