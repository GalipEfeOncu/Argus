#!/usr/bin/env bash
set -euo pipefail

scope="${1:-all}"

case "$scope" in
  docs)
    python3 .agents/skills/argus-development/scripts/check_docs.py
    ;;
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
    python3 .agents/skills/argus-development/scripts/check_docs.py
    npm run type-check
    (cd backend && .venv/bin/python3 -c "import app.main; print('backend import OK')")
    (cd src-tauri && cargo check)
    ;;
  *)
    echo "Usage: $0 {docs|frontend|backend|tauri|all}" >&2
    exit 2
    ;;
esac
