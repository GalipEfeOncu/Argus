#!/usr/bin/env python3
"""Validate local links and documentation contracts in repository-owned Markdown files.

Checks performed:
  1. Broken local link detection (original check).
  2. Stale contract reference check — warns (INFO) when a .md file links to
     contracts/session-events.schema.json or src/types/generated/session-events.ts
     and those files do not yet exist.  These are expected to be absent until
     Phase 0.2; the check is informational only and does not affect exit code.
  3. Malformed fenced code block check — errors when a file has an unclosed
     triple-backtick block.
  4. Fixed-pipeline-as-target check — errors when the pattern
     "Planner → Builder → Reviewer" (or ASCII arrow variant) appears near a
     "target" label in context that does not also contain a transitional marker
     such as "current", "transitional", "baseline", or "legacy".
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parents[4]
LINK_PATTERN = re.compile(r"!?(?:\[[^\]]*\])\(([^)]+)\)")
IGNORED_SCHEMES = ("http://", "https://", "mailto:", "tel:", "data:")

# Phase 0.2 generated contract paths (expected absent until that phase lands)
PHASE_02_CONTRACTS = (
    "contracts/session-events.schema.json",
    "src/types/generated/session-events.ts",
)

# Pipeline pattern (Unicode arrow or ASCII arrow, case-insensitive on role names)
FIXED_PIPELINE_RE = re.compile(
    r"Planner\s*(?:→|->)\s*Builder\s*(?:→|->)\s*Reviewer",
    re.IGNORECASE,
)

# "Target" indicator in a heading or label  (within CONTEXT_WINDOW lines of the match)
TARGET_LABEL_RE = re.compile(
    r"(?:^|\n)\s*(?:Target:|TARGET:)\s*$|^##\s+Target\b",
    re.IGNORECASE | re.MULTILINE,
)

# Transitional markers that excuse a fixed-pipeline mention
TRANSITIONAL_RE = re.compile(
    r"\b(?:current|transitional|baseline|legacy|migration)\b",
    re.IGNORECASE,
)

# Number of lines of context to check around a fixed-pipeline match for target/transitional markers
CONTEXT_WINDOW = 6


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


# ---------------------------------------------------------------------------
# Check 1 – Broken local links
# ---------------------------------------------------------------------------

def check_broken_links(files: list[Path]) -> list[str]:
    failures: list[str] = []
    for source in files:
        content = source.read_text(encoding="utf-8")
        for match in LINK_PATTERN.finditer(content):
            target = local_target(match.group(1))
            if target is None:
                continue
            destination = (source.parent / target).resolve()
            if not destination.exists():
                relative_source = source.relative_to(ROOT)
                failures.append(
                    f"{relative_source}: missing local link target {target!r}"
                )
    return failures


# ---------------------------------------------------------------------------
# Check 2 – Stale contract references (informational; does not affect exit code)
# ---------------------------------------------------------------------------

def check_stale_contract_refs(files: list[Path]) -> list[str]:
    """Return INFO messages for links to Phase 0.2 paths that do not exist yet."""
    infos: list[str] = []
    for source in files:
        content = source.read_text(encoding="utf-8")
        for contract_path in PHASE_02_CONTRACTS:
            if contract_path in content:
                full_path = ROOT / contract_path
                if not full_path.exists():
                    relative_source = source.relative_to(ROOT)
                    infos.append(
                        f"INFO {relative_source}: references '{contract_path}' which does not"
                        " exist yet (expected absent until Phase 0.2)"
                    )
    return infos


# ---------------------------------------------------------------------------
# Check 3 – Malformed fenced code blocks
# ---------------------------------------------------------------------------

def check_fenced_code_blocks(files: list[Path]) -> list[str]:
    """Detect unclosed triple-backtick fenced code blocks."""
    failures: list[str] = []
    fence_re = re.compile(r"^(`{3,})", re.MULTILINE)
    for source in files:
        content = source.read_text(encoding="utf-8")
        # Count each fence token; a well-formed file has an even number
        # because every opening fence has a matching closing fence.
        # We track depth: opening increments, a matching close decrements.
        lines = content.splitlines()
        open_fence: str | None = None
        open_line: int = 0
        for lineno, line in enumerate(lines, start=1):
            stripped = line.strip()
            m = re.match(r"^(`{3,})", stripped)
            if m:
                fence_token = m.group(1)
                if open_fence is None:
                    # Opening a fence
                    open_fence = fence_token
                    open_line = lineno
                elif stripped.startswith(open_fence) and re.match(r'^`+$', stripped):
                    # Matching close (same or longer backtick run, line is only backticks)
                    open_fence = None
                    open_line = 0
                # A fence token inside a fence is just content; ignore it.
        if open_fence is not None:
            relative_source = source.relative_to(ROOT)
            failures.append(
                f"{relative_source}: unclosed fenced code block opened at line {open_line}"
            )
    return failures


# ---------------------------------------------------------------------------
# Check 4 – Fixed pipeline described as target behavior
# ---------------------------------------------------------------------------

def check_fixed_pipeline_as_target(files: list[Path]) -> list[str]:
    """Error when Planner→Builder→Reviewer appears near a 'target' label without
    a transitional marker in the surrounding context."""
    failures: list[str] = []
    for source in files:
        content = source.read_text(encoding="utf-8")
        lines = content.splitlines()
        for lineno, line in enumerate(lines, start=1):
            if not FIXED_PIPELINE_RE.search(line):
                continue
            # Extract surrounding context
            start = max(0, lineno - 1 - CONTEXT_WINDOW)
            end = min(len(lines), lineno - 1 + CONTEXT_WINDOW + 1)
            context = "\n".join(lines[start:end])
            # If a transitional marker is present in context, this is expected
            if TRANSITIONAL_RE.search(context):
                continue
            # If a target label is present in context, this is a violation
            if TARGET_LABEL_RE.search(context):
                relative_source = source.relative_to(ROOT)
                failures.append(
                    f"{relative_source}:{lineno}: fixed pipeline described as target behavior"
                )
    return failures


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    files = markdown_files()
    failures: list[str] = []

    # Check 1
    broken = check_broken_links(files)
    failures.extend(broken)

    # Check 2 (informational only — print but do not add to failures)
    stale_infos = check_stale_contract_refs(files)
    for info in stale_infos:
        print(info)

    # Check 3
    bad_fences = check_fenced_code_blocks(files)
    failures.extend(bad_fences)

    # Check 4
    pipeline_violations = check_fixed_pipeline_as_target(files)
    failures.extend(pipeline_violations)

    if failures:
        print("Documentation check failed:")
        print("\n".join(f"- {failure}" for failure in failures))
        return 1

    print(f"Markdown checks OK ({len(files)} files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
