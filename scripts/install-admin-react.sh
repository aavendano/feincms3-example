#!/usr/bin/env bash
#
# Build the django-admin-react SPA bundle and install the package.
#
# The fork is installed from source, and its built bundle is not committed
# (static/admin_react/ is git-ignored), so a plain `pip install git+...`
# installs the Python code without the SPA and triggers
# django_admin_react.W002. This script runs the Vite build first so the
# bundle ends up inside the package before pip installs it.
#
# Usage:
#   scripts/install-admin-react.sh             # production: clone, build, install a wheel
#   scripts/install-admin-react.sh --editable  # development: build in the sibling checkout, pip install -e
#
# Environment:
#   DJANGO_ADMIN_REACT_REPO  git URL       (default: the aavendano fork)
#   DJANGO_ADMIN_REACT_REF   branch / tag  (default: main)
#   DJANGO_ADMIN_REACT_SRC   local checkout for --editable
#                            (default: ../django-admin-react next to this repo)
#
# Requires node >= 20 and pnpm (`corepack enable` provides it; see mise.toml).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO="${DJANGO_ADMIN_REACT_REPO:-https://github.com/aavendano/django-admin-react.git}"
REF="${DJANGO_ADMIN_REACT_REF:-main}"
PYTHON="${PYTHON:-python3}"

command -v pnpm >/dev/null 2>&1 || {
  echo "pnpm not found; run 'corepack enable' (node >= 20) or install pnpm" >&2
  exit 1
}

build() {
  (cd "$1/frontend" && pnpm install --frozen-lockfile && pnpm --filter @dar/web run build)
  if [[ ! -f "$1/django_admin_react/static/admin_react/.vite/manifest.json" ]]; then
    echo "Vite manifest missing after build in $1" >&2
    exit 2
  fi
}

if [[ "${1:-}" == "--editable" ]]; then
  SRC="${DJANGO_ADMIN_REACT_SRC:-$(dirname "$ROOT")/django-admin-react}"
  [[ -d "$SRC/frontend" ]] || {
    echo "No django-admin-react checkout at $SRC (set DJANGO_ADMIN_REACT_SRC)" >&2
    exit 1
  }
  build "$SRC"
  "$PYTHON" -m pip install -e "$SRC"
else
  WORK="$(mktemp -d)"
  trap 'rm -rf "$WORK"' EXIT
  git clone --quiet --depth 1 --branch "$REF" "$REPO" "$WORK/django-admin-react"
  build "$WORK/django-admin-react"
  "$PYTHON" -m pip install "$WORK/django-admin-react"
fi
