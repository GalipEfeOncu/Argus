"""Fixture coverage for every canonical target session wire branch."""

import json
from pathlib import Path
import re
from typing import Callable

import pytest
from pydantic import ValidationError

from app.schemas.session_commands import command_schema, parse_session_command
from app.schemas.session_events import (
    SAFE_RELATIVE_ARTIFACT_PATH_PATTERN,
    TIMEZONE_AWARE_ISO_TIMESTAMP_PATTERN,
    event_schema,
    parse_session_event,
)


FIXTURES = Path(__file__).parents[1] / "fixtures"
EVENT_TYPES = {
    "session.snapshot", "session.status_changed", "participant.status_changed",
    "message.created", "message.delta", "message.completed",
    "session.configuration_updated", "assignment.proposed", "assignment.created",
    "assignment.started", "assignment.completed", "assignment.failed",
    "assignment.cancelled", "handoff.created", "tool.requested", "tool.started",
    "tool.completed", "approval.requested", "approval.resolved", "limit.warning",
    "limit.reached", "decision.requested", "decision.recorded", "gate.status_changed",
    "artifact.diff_updated", "usage.updated", "error.created",
}
COMMAND_TYPES = {
    "message.send", "session.start", "session.pause", "session.resume", "session.cancel",
    "participant.interrupt", "approval.resolve", "session.configuration.update",
    "decision.resolve",
}


def fixture_paths(contract: str, validity: str) -> list[Path]:
    return sorted((FIXTURES / contract / validity).glob("*.json"))


def read_fixture(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("path", fixture_paths("session-events", "valid"))
def test_every_valid_event_fixture_parses_and_serializes_camel_case(path: Path) -> None:
    fixture = read_fixture(path)
    parsed = parse_session_event(fixture)
    assert parsed.model_dump(by_alias=True, mode="json", exclude_none=True) == fixture


@pytest.mark.parametrize("path", fixture_paths("session-events", "invalid"))
def test_every_invalid_event_fixture_is_rejected(path: Path) -> None:
    with pytest.raises(ValidationError):
        parse_session_event(read_fixture(path))


@pytest.mark.parametrize("path", fixture_paths("session-commands", "valid"))
def test_every_valid_command_fixture_parses_and_serializes_camel_case(path: Path) -> None:
    fixture = read_fixture(path)
    parsed = parse_session_command(fixture)
    assert parsed.model_dump(by_alias=True, mode="json", exclude_none=True) == fixture


@pytest.mark.parametrize("path", fixture_paths("session-commands", "invalid"))
def test_every_invalid_command_fixture_is_rejected(path: Path) -> None:
    with pytest.raises(ValidationError):
        parse_session_command(read_fixture(path))


def test_fixture_sets_cover_each_union_branch_once_per_validity() -> None:
    for contract, expected in (("session-events", EVENT_TYPES), ("session-commands", COMMAND_TYPES)):
        for validity in ("valid", "invalid"):
            paths = fixture_paths(contract, validity)
            assert {path.stem for path in paths} == expected
            assert len(paths) == len(expected)


def test_schemas_are_discriminated_and_do_not_expose_sensitive_payload_fields() -> None:
    for schema, expected in ((event_schema(), EVENT_TYPES), (command_schema(), COMMAND_TYPES)):
        assert schema["discriminator"]["propertyName"] == "type"
        assert set(schema["discriminator"]["mapping"]) == expected
        serialized = json.dumps(schema).lower()
        assert "providercredential" not in serialized
        assert "private_reasoning" not in serialized
        assert "privatereasoning" not in serialized


@pytest.mark.parametrize(
    ("parser", "value"),
    [
        (parse_session_event, {"type": "event.unknown"}),
        (parse_session_event, {"version": 1}),
        (parse_session_command, {"commandId": "cmd_01", "type": "command.unknown", "payload": {}}),
        (parse_session_command, {"commandId": "cmd_01", "payload": {}}),
    ],
)
def test_unrecognized_or_malformed_union_branches_are_rejected(
    parser: Callable[[dict[str, object]], object], value: dict[str, object]
) -> None:
    with pytest.raises(ValidationError):
        parser(value)


@pytest.mark.parametrize(
    ("parser", "fixture_path", "camel_case_key", "snake_case_key"),
    [
        (
            parse_session_event,
            FIXTURES / "session-events" / "valid" / "session.snapshot.json",
            "eventId",
            "event_id",
        ),
        (
            parse_session_command,
            FIXTURES / "session-commands" / "valid" / "message.send.json",
            "commandId",
            "command_id",
        ),
    ],
)
def test_snake_case_wire_input_is_rejected(
    parser: Callable[[dict[str, object]], object],
    fixture_path: Path,
    camel_case_key: str,
    snake_case_key: str,
) -> None:
    value = read_fixture(fixture_path)
    value[snake_case_key] = value.pop(camel_case_key)

    with pytest.raises(ValidationError):
        parser(value)


def test_event_envelope_requires_an_explicit_version() -> None:
    value = read_fixture(FIXTURES / "session-events" / "valid" / "session.snapshot.json")
    value.pop("version")

    with pytest.raises(ValidationError):
        parse_session_event(value)


@pytest.mark.parametrize("timestamp", [1_721_034_400, "2026-07-14T12:00:00", "2026-07-14 12:00:00Z"])
def test_event_timestamp_requires_timezone_aware_iso_text(timestamp: object) -> None:
    value = read_fixture(FIXTURES / "session-events" / "valid" / "session.snapshot.json")
    value["timestamp"] = timestamp

    with pytest.raises(ValidationError):
        parse_session_event(value)


@pytest.mark.parametrize(
    "file_path",
    ["/etc/passwd", "../outside.py", r"C:\\Windows\\system32", r"\\\\server\\share\\file", r"artifacts\\..\\outside.py"],
)
def test_artifact_diff_rejects_absolute_and_traversal_paths(file_path: str) -> None:
    value = read_fixture(FIXTURES / "session-events" / "valid" / "artifact.diff_updated.json")
    payload = value["payload"]
    assert isinstance(payload, dict)
    payload["filePath"] = file_path

    with pytest.raises(ValidationError):
        parse_session_event(value)


@pytest.mark.parametrize(
    "payload_update",
    [
        {"grantCapabilities": []},
        {"scopeSummary": "A bounded workspace scope."},
        {"grantCapabilities": ["workspace.write"], "scopeSummary": ""},
    ],
)
def test_approval_grant_requires_capabilities_and_scope(payload_update: dict[str, object]) -> None:
    value = read_fixture(FIXTURES / "session-commands" / "valid" / "approval.resolve.json")
    payload = value["payload"]
    assert isinstance(payload, dict)
    payload.clear()
    payload.update({"approvalId": "apr_01", "resolution": "grant"})
    payload.update(payload_update)

    with pytest.raises(ValidationError):
        parse_session_command(value)


@pytest.mark.parametrize("resolution", ["approve", "reject"])
def test_non_grant_approval_cannot_carry_explicit_capabilities(resolution: str) -> None:
    value = read_fixture(FIXTURES / "session-commands" / "valid" / "approval.resolve.json")
    payload = value["payload"]
    assert isinstance(payload, dict)
    payload.update({"resolution": resolution, "grantCapabilities": []})

    with pytest.raises(ValidationError):
        parse_session_command(value)


def test_command_schema_exposes_discriminated_approval_grant_semantics() -> None:
    schema = command_schema()
    approval_command = schema["$defs"]["ApprovalResolveCommand"]
    payload = approval_command["properties"]["payload"]

    assert payload["discriminator"]["propertyName"] == "resolution"
    assert set(payload["discriminator"]["mapping"]) == {"approve", "reject", "grant"}

    grant_payload = schema["$defs"]["ApprovalGrantPayload"]
    assert {"grantCapabilities", "scopeSummary"}.issubset(grant_payload["required"])
    for payload_name in ("ApprovalApprovePayload", "ApprovalRejectPayload"):
        assert "grantCapabilities" not in schema["$defs"][payload_name]["properties"]


@pytest.mark.parametrize(
    "timestamp",
    [
        "2026-07-14T12:00:00Z",
        "2026-07-14T12:00:00.123+03:00",
    ],
)
def test_exported_event_schema_timestamp_pattern_accepts_canonical_wire_text(timestamp: str) -> None:
    schema = event_schema()
    timestamp_schema = schema["$defs"]["SessionSnapshotEvent"]["properties"]["timestamp"]

    assert timestamp_schema["type"] == "string"
    assert timestamp_schema["pattern"] == TIMEZONE_AWARE_ISO_TIMESTAMP_PATTERN
    assert re.fullmatch(timestamp_schema["pattern"], timestamp)


@pytest.mark.parametrize(
    "timestamp",
    [1_721_034_400, "2026-07-14T12:00:00", "2026-07-14 12:00:00Z", "before 2026-07-14T12:00:00Z"],
)
def test_exported_event_schema_timestamp_pattern_rejects_noncanonical_wire_values(timestamp: object) -> None:
    schema = event_schema()
    timestamp_schema = schema["$defs"]["SessionSnapshotEvent"]["properties"]["timestamp"]

    assert not isinstance(timestamp, str) or re.fullmatch(timestamp_schema["pattern"], timestamp) is None


@pytest.mark.parametrize("file_path", ["artifact.py", "backend/app/main.py", r"artifacts\\diff.patch"])
def test_exported_event_schema_path_pattern_accepts_safe_relative_paths(file_path: str) -> None:
    schema = event_schema()
    path_schema = schema["$defs"]["ArtifactDiffUpdatedPayload"]["properties"]["filePath"]

    assert path_schema["pattern"] == SAFE_RELATIVE_ARTIFACT_PATH_PATTERN
    assert re.fullmatch(path_schema["pattern"], file_path)


@pytest.mark.parametrize(
    "file_path",
    ["/etc/passwd", "../outside.py", r"C:\\Windows\\system32", r"\\\\server\\share\\file", r"artifacts\\..\\outside.py"],
)
def test_exported_event_schema_path_pattern_rejects_unsafe_paths(file_path: str) -> None:
    schema = event_schema()
    path_schema = schema["$defs"]["ArtifactDiffUpdatedPayload"]["properties"]["filePath"]

    assert re.fullmatch(path_schema["pattern"], file_path) is None
