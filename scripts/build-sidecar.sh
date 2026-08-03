#!/usr/bin/env bash
set -euo pipefail

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
target_triple="${1:-$(rustc -vV | sed -n 's/^host: //p')}"
binary_suffix=""
if [[ "$target_triple" == *windows* ]]; then
  binary_suffix=".exe"
fi
output_dir="$repository_root/src-tauri/binaries"
work_dir="$repository_root/backend/build/pyinstaller-$target_triple"
dist_dir="$repository_root/backend/dist/pyinstaller-$target_triple"
migration_data=()
for migration in "$repository_root"/backend/app/db/migrations/*.py; do
  migration_data+=(--add-data "$migration:app/db/migrations")
done

mkdir -p "$output_dir" "$work_dir" "$dist_dir"
cd "$repository_root/backend"
uv run --no-dev --extra packaging pyinstaller \
  --clean \
  --noconfirm \
  --onefile \
  "${migration_data[@]}" \
  --name "argus-backend-$target_triple" \
  --distpath "$dist_dir" \
  --workpath "$work_dir" \
  --specpath "$work_dir" \
  --exclude-module pytest \
  --exclude-module langgraph \
  --exclude-module langchain_openai \
  --exclude-module langchain_anthropic \
  --exclude-module langchain_google_genai \
  --exclude-module httptools \
  --exclude-module uvloop \
  --exclude-module watchfiles \
  --exclude-module pytest_asyncio \
  sidecar_main.py
install -m 755 \
  "$dist_dir/argus-backend-$target_triple$binary_suffix" \
  "$output_dir/argus-backend-$target_triple$binary_suffix"
uv run --no-dev --extra packaging python "$repository_root/scripts/sidecar-attribution.py" \
  "$output_dir/argus-backend-$target_triple$binary_suffix" \
  "$work_dir/argus-backend-$target_triple/PKG-00.toc" \
  "$target_triple" \
  "$repository_root/benchmarks/results/sidecar-$target_triple-attribution.json"
