#!/usr/bin/env bash
# Build NoETL UI assets into ui/static
#
# Usage:
#   tools/build_ui.sh [--with-server] [-m dev|prod] [-p PORT]
#
# Notes:
# - This is a lightweight builder intended for local/dev usage and CI.
# - Build and versioning scripts live under tools/; PyPI helpers live under tools/pypi.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
UI_SRC_DIR="$PROJECT_ROOT/ui-src"
UI_OUT_DIR="$PROJECT_ROOT/ui/static"
MODE="prod"
PORT="8080"
WITH_SERVER=false

print_help() {
  cat <<EOF
Build NoETL UI assets.

Options:
  --with-server        Also start the dev server after build (noop in prod build)
  -m, --mode MODE      Build mode: dev|prod (default: prod)
  -p, --port PORT      Dev server port (default: 8080) [noop in prod build]
  -h, --help           Show this help and exit
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --with-server)
      WITH_SERVER=true
      shift
      ;;
    -m|--mode)
      MODE="${2:-$MODE}"; shift 2 ;;
    -p|--port)
      PORT="${2:-$PORT}"; shift 2 ;;
    -h|--help)
      print_help; exit 0 ;;
    *)
      echo "Unknown argument: $1" >&2
      print_help
      exit 1
      ;;
  esac
done

if [[ ! -d "$UI_SRC_DIR" ]]; then
  echo "[build_ui] ui-src directory not found at $UI_SRC_DIR — nothing to build. Skipping."
  exit 0
fi

mkdir -p "$UI_OUT_DIR"

# Detect package manager
PKG_MGR="npm"
if command -v pnpm >/dev/null 2>&1; then
  PKG_MGR="pnpm"
elif command -v yarn >/dev/null 2>&1; then
  PKG_MGR="yarn"
fi

pushd "$UI_SRC_DIR" >/dev/null

# Install deps (best-effort, do not fail CI if lockfile mismatch)
if [[ "$PKG_MGR" == "pnpm" ]]; then
  pnpm install --frozen-lockfile || pnpm install || true
elif [[ "$PKG_MGR" == "yarn" ]]; then
  yarn install --frozen-lockfile || yarn install || true
else
  npm ci || npm install || true
fi

# Build
if [[ "$MODE" == "dev" ]]; then
  if npm run | grep -qE "build:dev"; then
    $PKG_MGR run build:dev
  else
    # Fallback to build
    $PKG_MGR run build
  fi
else
  if npm run | grep -qE "build:prod"; then
    $PKG_MGR run build:prod
  else
    $PKG_MGR run build
  fi
fi

# Copy artifacts if a conventional dist exists
if [[ -d "dist" ]]; then
  rsync -a --delete "dist/" "$UI_OUT_DIR/"
elif [[ -d "build" ]]; then
  rsync -a --delete "build/" "$UI_OUT_DIR/"
fi

popd >/dev/null

echo "[build_ui] UI build complete → $UI_OUT_DIR"

# Optional dev server
if [[ "$WITH_SERVER" == true ]]; then
  echo "[build_ui] --with-server requested. Starting dev server on :$PORT"
  pushd "$UI_SRC_DIR" >/dev/null
  if npm run | grep -qE "dev"; then
    PORT="$PORT" $PKG_MGR run dev
  elif npm run | grep -qE "start"; then
    PORT="$PORT" $PKG_MGR start
  else
    echo "No dev/start script found in ui-src package.json; exiting."
  fi
  popd >/dev/null
fi
