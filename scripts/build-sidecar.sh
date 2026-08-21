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

native_path() {
  case "$(uname -s)" in
    CYGWIN*|MINGW*|MSYS*)
      cygpath -m "$1"
      ;;
    *)
      printf '%s\n' "$1"
      ;;
  esac
}

migration_data=()
for migration in "$repository_root"/backend/app/db/migrations/*.py; do
  migration_data+=(--add-data "$(native_path "$migration"):app/db/migrations")
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
  --hidden-import langchain_openai \
  --hidden-import langchain_anthropic \
  --hidden-import langchain_google_genai \
  --copy-metadata langchain-openai \
  --copy-metadata langchain-anthropic \
  --copy-metadata langchain-google-genai \
  --exclude-module httptools \
  --exclude-module uvloop \
  --exclude-module watchfiles \
  --exclude-module pytest_asyncio \
  sidecar_main.py
install -m 755 \
  "$dist_dir/argus-backend-$target_triple$binary_suffix" \
  "$output_dir/argus-backend-$target_triple$binary_suffix"
python "$repository_root/scripts/smoke-sidecar.py" \
  "$output_dir/argus-backend-$target_triple$binary_suffix" \
  --providers-only
uv run --no-dev --extra packaging python "$repository_root/scripts/sidecar-attribution.py" \
  "$output_dir/argus-backend-$target_triple$binary_suffix" \
  "$work_dir/argus-backend-$target_triple/Analysis-00.toc" \
  "$target_triple" \
  "$repository_root/benchmarks/results/sidecar-$target_triple-attribution.json"
