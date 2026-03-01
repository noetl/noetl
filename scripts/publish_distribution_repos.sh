#!/usr/bin/env bash
set -euo pipefail

VERSION="${1:-}"
HOMEBREW_TARGET="${2:-${HOME}/projects/noetl/homebrew-tap}"
APT_TARGET="${3:-${HOME}/projects/noetl/apt}"
APT_ARCH="${4:-auto}"
REFRESH_LINKS="${5:-true}"
PUSH_CHANGES="${6:-true}"
HOMEBREW_REMOTE="${7:-git@github.com:noetl/homebrew-tap.git}"
APT_REMOTE="${8:-git@github.com:noetl/apt.git}"

if [[ -z "${VERSION}" ]]; then
  echo "Usage: $0 <version> [homebrew_target] [apt_target] [apt_arch] [refresh_links] [push_changes] [homebrew_remote] [apt_remote]"
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

resolve_arch() {
  if [[ "${APT_ARCH}" != "auto" ]]; then
    echo "${APT_ARCH}"
    return
  fi
  case "$(uname -m)" in
    arm64|aarch64) echo "arm64" ;;
    x86_64|amd64) echo "amd64" ;;
    *) echo "amd64" ;;
  esac
}

ensure_link() {
  local link_path="$1"
  local target_path="$2"

  if [[ ! -d "${target_path}" ]]; then
    echo "Target repository not found: ${target_path}"
    exit 1
  fi

  if [[ -L "${link_path}" ]]; then
    ln -sfn "${target_path}" "${link_path}"
    return
  fi

  if [[ -e "${link_path}" ]]; then
    echo "Path exists and is not a symlink: ${link_path}"
    exit 1
  fi

  ln -s "${target_path}" "${link_path}"
}

ensure_git_repo() {
  local repo_path="$1"
  local remote_url="$2"

  if git -C "${repo_path}" rev-parse --git-dir >/dev/null 2>&1; then
    return
  fi

  if [[ -e "${repo_path}" ]]; then
    if [[ -n "$(find "${repo_path}" -mindepth 1 -maxdepth 1 -print -quit 2>/dev/null)" ]]; then
      local backup_path="${repo_path}.backup.$(date +%Y%m%d%H%M%S)"
      echo "Non-git directory detected at ${repo_path}, moving to ${backup_path}"
      mv "${repo_path}" "${backup_path}"
    else
      rmdir "${repo_path}" 2>/dev/null || true
    fi
  fi

  mkdir -p "$(dirname "${repo_path}")"
  echo "Cloning ${remote_url} -> ${repo_path}"
  git clone "${remote_url}" "${repo_path}"
}

sync_main() {
  local repo_path="$1"
  git -C "${repo_path}" fetch origin
  git -C "${repo_path}" checkout main
  git -C "${repo_path}" pull --ff-only origin main
}

commit_if_changed() {
  local repo_path="$1"
  local message="$2"

  if [[ -n "$(git -C "${repo_path}" status --porcelain)" ]]; then
    git -C "${repo_path}" add -A
    git -C "${repo_path}" commit -m "${message}"
    if [[ "${PUSH_CHANGES}" == "true" ]]; then
      git -C "${repo_path}" push origin main
    fi
  else
    echo "No changes detected in ${repo_path}"
  fi
}

if [[ "${REFRESH_LINKS}" == "true" ]]; then
  ensure_git_repo "${HOMEBREW_TARGET}" "${HOMEBREW_REMOTE}"
  ensure_git_repo "${APT_TARGET}" "${APT_REMOTE}"
  ensure_link "${REPO_ROOT}/homebrew-tap" "${HOMEBREW_TARGET}"
  ensure_link "${REPO_ROOT}/apt" "${APT_TARGET}"
fi

ensure_git_repo "${HOMEBREW_TARGET}" "${HOMEBREW_REMOTE}"
ensure_git_repo "${APT_TARGET}" "${APT_REMOTE}"

sync_main "${HOMEBREW_TARGET}"
sync_main "${APT_TARGET}"

echo "Updating Homebrew formula for v${VERSION}"
"${REPO_ROOT}/scripts/homebrew_publish.sh" "${VERSION}"
mkdir -p "${HOMEBREW_TARGET}/Formula"
cp "${REPO_ROOT}/homebrew/noetl.rb" "${HOMEBREW_TARGET}/Formula/noetl.rb"
commit_if_changed "${HOMEBREW_TARGET}" "noetl ${VERSION}"

ARCH="$(resolve_arch)"
DEB_FILE="${REPO_ROOT}/build/deb/noetl_${VERSION}-1_${ARCH}.deb"
echo "Building and publishing APT metadata for v${VERSION} (${ARCH})"
if [[ -f "${DEB_FILE}" ]]; then
  echo "Reusing existing package: ${DEB_FILE}"
else
  "${REPO_ROOT}/docker/release/build-deb-docker.sh" "${VERSION}"
fi
"${REPO_ROOT}/docker/release/publish-apt-docker.sh" "${VERSION}" "${ARCH}" "${APT_TARGET}/pool/main"

if [[ ! -d "${REPO_ROOT}/apt-repo" ]]; then
  echo "APT repository output not found: ${REPO_ROOT}/apt-repo"
  exit 1
fi

rsync -a --delete --exclude='.git' "${REPO_ROOT}/apt-repo/" "${APT_TARGET}/"
commit_if_changed "${APT_TARGET}" "noetl ${VERSION} (${ARCH})"

echo "Done."
