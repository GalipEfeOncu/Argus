#!/usr/bin/env python3
"""Run pytest and expose failing node IDs as GitHub Actions annotations."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path


def _workflow_escape(value: str) -> str:
    return value.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: run-pytest-ci.py <project-directory>", file=sys.stderr)
        return 2

    project = Path(sys.argv[1]).resolve()
    with tempfile.TemporaryDirectory(prefix="argus-pytest-") as temporary:
        report = Path(temporary) / "report.xml"
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", f"--junitxml={report}"],
            cwd=project,
            check=False,
        )
        if result.returncode == 0 or not report.is_file():
            return result.returncode

        for case in ET.parse(report).getroot().iter("testcase"):
            failure = case.find("failure")
            if failure is None:
                failure = case.find("error")
            if failure is None:
                continue
            node_id = f"{case.get('classname', 'pytest')}.{case.get('name', 'unknown')}"
            message = failure.get("message") or (failure.text or "pytest failed").strip().splitlines()[-1]
            print(f"::error title=pytest failure::{_workflow_escape(f'{node_id}: {message}')}")
        return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
