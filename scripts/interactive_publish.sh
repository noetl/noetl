#!/bin/bash
# Interactive NoETL Publishing Workflow
# This script provides interactive process for publishing NoETL to PyPI

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" &> /dev/null && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_ROOT"

show_banner() {
    echo -e "${BLUE}${BOLD}"
    echo "╔══════════════════════════════════════════════════════════════╗"
    echo "║                 NoETL PyPI Publishing Wizard                 ║"
    echo "║                                                              ║"
    echo "║  This script will guide through the process of               ║"
    echo "║  publishing NoETL to PyPI with all safety checks             ║"
    echo "╚══════════════════════════════════════════════════════════════╝"
    echo -e "${NC}"
}

get_current_status() {
    echo -e "${CYAN}Current Project Status${NC}"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    local current_version=$(python3 -c "
import re
try:
    with open('pyproject.toml', 'r') as f:
        content = f.read()
        match = re.search(r'version\s*=\s*[\"\\']([^\"\\']*)[\"\\']\s*', content)
        print(match.group(1) if match else 'unknown')
except FileNotFoundError:
    print('unknown')
")

    echo -e "${BLUE}Current version:${NC} $current_version"

    if command -v git &> /dev/null && [ -d ".git" ]; then
        local git_status=$(git status --porcelain | wc -l | tr -d ' ')
        if [ "$git_status" -eq 0 ]; then
            echo -e "${GREEN}Git status:${NC} Clean (no uncommitted changes)"
        else
            echo -e "${YELLOW}Git status:${NC} $git_status uncommitted changes"
        fi

        local current_branch=$(git branch --show-current)
        echo -e "${BLUE}Current branch:${NC} $current_branch"
    fi

    if [ -d "ui/static" ] && [ "$(ls -A ui/static)" ]; then
        local ui_files=$(find ui/static -type f | wc -l | tr -d ' ')
        echo -e "${GREEN}UI status:${NC} Built ($ui_files files)"
    else
        echo -e "${YELLOW}UI status:${NC} Not built or missing"
    fi

    if [ -d "dist" ] && [ "$(ls -A dist)" ]; then
        local dist_files=$(ls dist | wc -l | tr -d ' ')
        echo -e "${GREEN}Last build:${NC} $dist_files files in dist/"
    else
        echo -e "${YELLOW}Last build:${NC} No build artifacts found"
    fi

    echo ""
}

select_option() {
    local prompt="$1"
    shift
    local options=("$@")

    echo -e "${CYAN}$prompt${NC}"
    for i in "${!options[@]}"; do
        echo "  $((i+1)). ${options[i]}"
    done

    while true; do
        read -p "Select option [1-${#options[@]}]: " choice
        if [[ "$choice" =~ ^[0-9]+$ ]] && [ "$choice" -ge 1 ] && [ "$choice" -le "${#options[@]}" ]; then
            return $((choice-1))
        else
            echo -e "${RED}Invalid choice. Please select 1-${#options[@]}${NC}"
        fi
    done
}

handle_version() {
    echo -e "${CYAN}Version Management${NC}"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

    local current_version=$(python3 -c "
import re
with open('pyproject.toml', 'r') as f:
    content = f.read()
    match = re.search(r'version\s*=\s*[\"\\']([^\"\\']*)[\"\\']\s*', content)
    print(match.group(1) if match else 'unknown')
")

    echo -e "${BLUE}Current version:${NC} $current_version"

    options=(
        "Keep current version ($current_version)"
        "Patch increment (e.g., 1.0.0 → 1.0.1)"
        "Minor increment (e.g., 1.0.0 → 1.1.0)"
        "Major increment (e.g., 1.0.0 → 2.0.0)"
        "Set custom version"
    )

    select_option "What would you like to do with the version?" "${options[@]}"
    local choice=$?

    case $choice in
        0)
            echo -e "${GREEN}Keeping current version: $current_version${NC}"
            ;;
        1)
            echo -e "${BLUE}Incrementing patch version...${NC}"
            "$SCRIPT_DIR/update_version.py" patch
            ;;
        2)
            echo -e "${BLUE}Incrementing minor version...${NC}"
            "$SCRIPT_DIR/update_version.py" minor
            ;;
        3)
            echo -e "${BLUE}Incrementing major version...${NC}"
            "$SCRIPT_DIR/update_version.py" major
            ;;
        4)
            read -p "Enter new version (e.g., 1.2.3): " new_version
            if [[ "$new_version" =~ ^[0-9]+\.[0-9]+\.[0-9]+.*$ ]]; then
                echo -e "${BLUE}Setting version to $new_version...${NC}"
                "$SCRIPT_DIR/update_version.py" "$new_version"
            else
                echo -e "${RED}Invalid version format${NC}"
                return 1
            fi
            ;;
    esac

    echo ""
}

run_preflight_checks() {
    echo -e "${CYAN}Pre-flight Checks${NC}"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

    local checks_passed=0
    local total_checks=6
    echo -n "Checking required files... "
    if [ -f "pyproject.toml" ] && [ -f "README.md" ] && [ -f "LICENSE" ]; then
        echo -e "${GREEN} ${NC}"
        ((checks_passed++))
    else
        echo -e "${RED} ${NC}"
        echo "  Missing: $([ ! -f "pyproject.toml" ] && echo "pyproject.toml ") $([ ! -f "README.md" ] && echo "README.md ") $([ ! -f "LICENSE" ] && echo "LICENSE")"
    fi

    echo -n "Checking build dependencies... "
    if python3 -c "import build, twine" &> /dev/null; then
        echo -e "${GREEN} ${NC}"
        ((checks_passed++))
    else
        echo -e "${YELLOW} ${NC}"
        echo "  Will install missing dependencies automatically"
        ((checks_passed++))
    fi

    echo -n "Checking package structure... "
    if [ -d "noetl" ] && [ -f "noetl/__init__.py" ]; then
        echo -e "${GREEN} ${NC}"
        ((checks_passed++))
    else
        echo -e "${RED} ${NC}"
    fi

    echo -n "Checking UI components... "
    if [ -d "ui" ]; then
        echo -e "${GREEN} ${NC}"
        ((checks_passed++))
    else
        echo -e "${YELLOW} ${NC}"
        echo "  UI directory missing, will create minimal UI"
        ((checks_passed++))
    fi

    echo -n "Checking git status... "
    if command -v git &> /dev/null && [ -d ".git" ]; then
        if [ -z "$(git status --porcelain)" ]; then
            echo -e "${GREEN} ${NC}"
            ((checks_passed++))
        else
            echo -e "${YELLOW} ${NC}"
            echo "  Uncommitted changes detected"
            read -p "  Continue anyway? (y/N): " -n 1 -r
            echo
            if [[ $REPLY =~ ^[Yy]$ ]]; then
                ((checks_passed++))
            fi
        fi
    else
        echo -e "${YELLOW} ${NC}"
        echo "  Not a git repository"
        ((checks_passed++))
    fi

    echo -n "Checking PyPI credentials... "
    if [ -f "$HOME/.pypirc" ] || [ -n "$PYPI_TOKEN" ]; then
        echo -e "${GREEN}✅${NC}"
        ((checks_passed++))
    else
        echo -e "${YELLOW} ${NC}"
        echo "  No PyPI credentials found. You'll need to provide them during upload."
        read -p "  Continue anyway? (y/N): " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            ((checks_passed++))
        fi
    fi

    echo ""
    echo -e "${BLUE}Checks passed: $checks_passed/$total_checks${NC}"

    if [ $checks_passed -lt $total_checks ]; then
        echo -e "${YELLOW}  Some checks failed. You can continue, but there might be issues.${NC}"
        read -p "Continue anyway? (y/N): " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            echo -e "${RED} Aborting publication${NC}"
            exit 1
        fi
    fi

    echo ""
}

handle_build() {
    echo -e "${CYAN}  Build Process${NC}"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

    options=(
        "Build everything (UI + Package)"
        "Build package only (skip UI)"
        "Skip build (use existing)"
    )

    select_option "How would you like to build?" "${options[@]}"
    local choice=$?

    case $choice in
        0)
            echo -e "${BLUE} Building UI...${NC}"
            "$SCRIPT_DIR/build_ui.sh"
            echo -e "${BLUE} Building package...${NC}"
            "$SCRIPT_DIR/build_package.sh"
            ;;
        1)
            echo -e "${BLUE} Building package only...${NC}"
            "$SCRIPT_DIR/build_package.sh"
            ;;
        2)
            echo -e "${YELLOW}️  Using existing build${NC}"
            if [ ! -d "dist" ] || [ -z "$(ls -A dist)" ]; then
                echo -e "${RED} No existing build found${NC}"
                return 1
            fi
            ;;
    esac

    echo ""
}

handle_publication() {
    echo -e "${CYAN} Publication Workflow${NC}"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

    options=(
        "Test on TestPyPI first (recommended)"
        "Publish directly to PyPI"
        "Dry run (show what would be published)"
    )

    select_option "How would you like to publish?" "${options[@]}"
    local choice=$?

    local current_version=$(python3 -c "
import re
with open('pyproject.toml', 'r') as f:
    content = f.read()
    match = re.search(r'version\s*=\s*[\"\\']([^\"\\']*)[\"\\']\s*', content)
    print(match.group(1) if match else 'unknown')
")

    case $choice in
        0)
            echo -e "${BLUE} Publishing to TestPyPI...${NC}"
            "$SCRIPT_DIR/pypi_publish.sh" --test "$current_version"

            echo -e "${CYAN}TestPyPI publication completed!${NC}"
            read -p "Test the package and then press Enter to continue to PyPI (or Ctrl+C to abort)..."

            echo -e "${BLUE} Publishing to PyPI...${NC}"
            "$SCRIPT_DIR/pypi_publish.sh" "$current_version"
            ;;
        1)
            echo -e "${YELLOW}  Publishing directly to PyPI${NC}"
            read -p "Are you sure? This will make the package immediately available. (y/N): " -n 1 -r
            echo
            if [[ $REPLY =~ ^[Yy]$ ]]; then
                echo -e "${BLUE} Publishing to PyPI...${NC}"
                "$SCRIPT_DIR/pypi_publish.sh" "$current_version"
            else
                echo -e "${YELLOW} Publication cancelled${NC}"
                return 1
            fi
            ;;
        2)
            echo -e "${BLUE} Running dry run...${NC}"
            "$SCRIPT_DIR/pypi_publish.sh" --dry-run "$current_version"
            ;;
    esac

    echo ""
}

show_post_publication() {
    local version=$1

    echo -e "${CYAN} Publication Complete!${NC}"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo -e "${GREEN} NoETL v$version has been published to PyPI!${NC}"
    echo ""
    echo -e "${BLUE} Next Steps:${NC}"
    echo "  1. Test installation:"
    echo "     ${CYAN}pip install noetl==$version${NC}"
    echo ""
    echo "  2. Verify the UI works:"
    echo "     ${CYAN}noetl server --port 8082${NC}"
    echo "     ${CYAN}# Visit http://localhost:8082/ui${NC}"
    echo ""
    echo "  3. Update documentation if needed"
    echo ""
    echo "  4. Create a Git tag for this release:"
    echo "     ${CYAN}git tag v$version${NC}"
    echo "     ${CYAN}git push origin v$version${NC}"
    echo ""
    echo -e "${BLUE} Resources:${NC}"
    echo "  • PyPI page: https://pypi.org/project/noetl/$version/"
    echo "  • Installation: pip install noetl"
    echo "  • Documentation: Check README.md for usage instructions"
    echo ""
}

main() {
    show_banner
    get_current_status

    if handle_version; then
        echo -e "${GREEN} Version management completed${NC}"
    else
        echo -e "${RED} Version management failed${NC}"
        exit 1
    fi

    run_preflight_checks

    if handle_build; then
        echo -e "${GREEN} Build completed${NC}"
    else
        echo -e "${RED} Build failed${NC}"
        exit 1
    fi

    if handle_publication; then
        echo -e "${GREEN} Publication completed${NC}"

        local final_version=$(python3 -c "
import re
with open('pyproject.toml', 'r') as f:
    content = f.read()
    match = re.search(r'version\s*=\s*[\"\\']([^\"\\']*)[\"\\']\s*', content)
    print(match.group(1) if match else 'unknown')
")

        show_post_publication "$final_version"
    else
        echo -e "${RED} Publication failed${NC}"
        exit 1
    fi
}

trap 'echo -e "\n${YELLOW} Publication cancelled by user${NC}"; exit 130' INT

main
