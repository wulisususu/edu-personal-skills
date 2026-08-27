#!/usr/bin/env bash
# Thin POSIX launcher. All refresh logic lives in refresh.py.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="${PYTHON:-python3}"

command -v "$PYTHON_BIN" >/dev/null 2>&1 || {
  echo "ERROR: Python not found: $PYTHON_BIN" >&2
  exit 1
}

exec "$PYTHON_BIN" "$SCRIPT_DIR/refresh.py" "$@"
