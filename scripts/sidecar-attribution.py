"""Attribute a frozen sidecar's final artifact and PyInstaller input groups."""

from __future__ import annotations

import ast
from hashlib import sha256
import json
from pathlib import Path
import sys

import PyInstaller


EXCLUDED_MODULES = [
    "pytest",
    "pytest_asyncio",
    "langgraph",
    "langchain_openai",
    "langchain_anthropic",
    "langchain_google_genai",
    "httptools",
    "uvloop",
    "watchfiles",
]


def category(source: Path) -> str:
    value = source.as_posix()
    if "/backend/app/" in value or value.endswith("/backend/sidecar_main.py"):
        return "argus-code"
    if "site-packages" in value:
        return "base-dependencies"
    if "python" in value or source.name.startswith("libpython"):
        return "python-runtime"
    return "platform-runtime"


def main() -> None:
    if len(sys.argv) != 5:
        raise SystemExit("Usage: sidecar-attribution.py <binary> <PKG-00.toc> <target> <output>")
    binary, toc, target, output = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3], Path(sys.argv[4])
    artifact = binary.read_bytes()
    entries = ast.literal_eval(toc.read_text(encoding="utf-8"))[2]
    groups: dict[str, dict[str, int]] = {}
    seen: set[Path] = set()
    for entry in entries:
        if not isinstance(entry, tuple) or len(entry) < 2 or not isinstance(entry[1], str):
            continue
        source = Path(entry[1])
        if source in seen or not source.is_file():
            continue
        seen.add(source)
        group = groups.setdefault(category(source), {"entries": 0, "sourceBytes": 0})
        group["entries"] += 1
        group["sourceBytes"] += source.stat().st_size
    report = {
        "schemaVersion": 1,
        "targetTriple": target,
        "tool": {"name": "PyInstaller", "version": PyInstaller.__version__},
        "artifact": {"fileName": binary.name, "bytes": len(artifact), "sha256": sha256(artifact).hexdigest()},
        "compositionInputs": [{"category": name, **values} for name, values in sorted(groups.items())],
        "excludedModules": EXCLUDED_MODULES,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
