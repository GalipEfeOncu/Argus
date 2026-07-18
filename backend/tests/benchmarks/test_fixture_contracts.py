"""Generated benchmark sessions must remain valid canonical wire events."""

import json
from pathlib import Path
import subprocess

from app.schemas.session_events import parse_session_event


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
FIXTURE_GENERATOR = REPOSITORY_ROOT / "scripts" / "benchmarks" / "generate-fixtures.mjs"


def test_generated_session_fixtures_parse_as_canonical_events(tmp_path: Path) -> None:
    subprocess.run(
        ["node", str(FIXTURE_GENERATOR), "--output-dir", str(tmp_path)],
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    for fixture_name, expected_count in (("session-100.json", 100), ("session-10000.json", 10_000)):
        events = json.loads((tmp_path / fixture_name).read_text(encoding="utf-8"))
        assert len(events) == expected_count
        for event in events:
            parsed = parse_session_event(event)
            assert parsed.type == "participant.status_changed"
            assert parsed.model_dump(by_alias=True, mode="json", exclude_none=True) == event
