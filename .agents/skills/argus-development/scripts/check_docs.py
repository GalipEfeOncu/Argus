#!/usr/bin/env python3
"""Validate local links in repository-owned Markdown files."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parents[4]
LINK_PATTERN = re.compile(r"!?(?:\[[^\]]*\])\(([^)]+)\)")
IGNORED_SCHEMES = ("http://", "https://", "mailto:", "tel:", "data:")


def markdown_files() -> list[Path]:
    result = subprocess.run(
        [
            "git",
            "ls-files",
            "--cached",
            "--others",
            "--exclude-standard",
            "*.md",
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    candidates = [ROOT / line for line in result.stdout.splitlines() if line]
    return [path for path in candidates if path.is_file()]


def local_target(raw_target: str) -> str | None:
    target = raw_target.strip().split(maxsplit=1)[0].strip("<>")
    if not target or target.startswith("#") or target.startswith(IGNORED_SCHEMES):
        return None
    return unquote(target.split("#", maxsplit=1)[0])


def main() -> int:
    failures: list[str] = []
    files = markdown_files()

    for source in files:
        content = source.read_text(encoding="utf-8")
        for match in LINK_PATTERN.finditer(content):
            target = local_target(match.group(1))
            if target is None:
                continue
            destination = (source.parent / target).resolve()
            if not destination.exists():
                relative_source = source.relative_to(ROOT)
                failures.append(f"{relative_source}: missing local link target {target!r}")

    if failures:
        print("Markdown link validation failed:")
        print("\n".join(f"- {failure}" for failure in failures))
        return 1

    print(f"Markdown links OK ({len(files)} files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
