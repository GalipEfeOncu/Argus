#!/usr/bin/env bash
set -euo pipefail

scope="${1:-all}"

case "$scope" in
  frontend)
    npm run type-check
    ;;
  backend)
    (cd backend && .venv/bin/python3 -c "import app.main; print('backend import OK')")
    ;;
  tauri)
    (cd src-tauri && cargo check)
    ;;
  all)
    npm run type-check
    (cd backend && .venv/bin/python3 -c "import app.main; print('backend import OK')")
    (cd src-tauri && cargo check)
    ;;
  *)
    echo "Usage: $0 {frontend|backend|tauri|all}" >&2
    exit 2
    ;;
esac
