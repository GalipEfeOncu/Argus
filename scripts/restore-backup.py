#!/usr/bin/env python3
"""Restore an Argus pre-migration backup after explicit operator confirmation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "backend"))

from app.db.backup import restore_backup  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path, help="Path to the backup JSON manifest")
    parser.add_argument("--database", type=Path, help="Override the database destination")
    parser.add_argument("--confirm", action="store_true", help="Confirm the app is stopped and restore")
    args = parser.parse_args()
    if not args.confirm:
        parser.error("--confirm is required; stop Argus before restoring")

    manifest = json.loads(args.manifest.read_text())
    backup = Path(str(manifest["backup_path"]))
    if not backup.is_file():
        sibling = args.manifest.with_suffix(".db")
        if sibling.is_file():
            backup = sibling
    database = args.database or Path(str(manifest["database_path"]))
    displaced = restore_backup(backup, database, str(manifest["sha256"]))
    print(f"Restored {database}")
    if displaced is not None:
        print(f"Previous database retained at {displaced}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
