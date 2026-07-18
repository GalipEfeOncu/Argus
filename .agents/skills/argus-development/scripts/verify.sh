#!/usr/bin/env bash
set -euo pipefail

scope="${1:-all}"

case "$scope" in
  docs)
    python3 .agents/skills/argus-development/scripts/check_docs.py
    ;;
  frontend)
    npm run type-check
    npm run test
    npm run build
    ;;
  backend)
    (cd backend && .venv/bin/python3 -c "import app.main; print('backend import OK')")
    (cd backend && .venv/bin/python3 -m pytest -q)
    ;;
  tauri)
    (cd src-tauri && cargo check)
    ;;
  all)
    python3 .agents/skills/argus-development/scripts/check_docs.py
    npm run type-check
    npm run test
    npm run build
    (cd backend && .venv/bin/python3 -c "import app.main; print('backend import OK')")
    (cd backend && .venv/bin/python3 -m pytest -q)
    (cd src-tauri && cargo check)
    ;;
  *)
    echo "Usage: $0 {docs|frontend|backend|tauri|all}" >&2
    exit 2
    ;;
esac
