"""Durable control-plane tables required by Phase 2.1."""

from __future__ import annotations

import aiosqlite


async def _columns(db: aiosqlite.Connection, table: str) -> set[str]:
    async with db.execute(f"PRAGMA table_info({table})") as cursor:
        return {row[1] for row in await cursor.fetchall()}


async def _add_column_if_missing(db: aiosqlite.Connection, table: str, definition: str) -> None:
    name = definition.split()[0]
    if name not in await _columns(db, table):
        await db.execute(f"ALTER TABLE {table} ADD COLUMN {definition}")


async def apply(db: aiosqlite.Connection) -> None:
    # Retain prototype fields until its transitional HTTP/WebSocket endpoints are retired.
    for definition in (
        "project_id TEXT REFERENCES projects(id)",
        "goal TEXT",
        "policy_snapshot_json TEXT NOT NULL DEFAULT '{}'",
        "workspace_metadata_json TEXT NOT NULL DEFAULT '{}'",
        "counters_json TEXT NOT NULL DEFAULT '{}'",
        "summary TEXT",
        "created_at_ms INTEGER NOT NULL DEFAULT 0 CHECK (created_at_ms >= 0)",
        "updated_at_ms INTEGER NOT NULL DEFAULT 0 CHECK (updated_at_ms >= 0)",
    ):
        await _add_column_if_missing(db, "sessions", definition)

    # The previous prototype wrote Unix seconds.  Its retained compatibility
    # columns now use the same millisecond unit as the durable schema.
    await db.execute("""
        UPDATE sessions
        SET goal = COALESCE(goal, task),
            created_at_ms = CASE WHEN created_at_ms = 0 THEN CAST(started_at * 1000 AS INTEGER) ELSE created_at_ms END,
            updated_at_ms = CASE WHEN updated_at_ms = 0 THEN CAST(started_at * 1000 AS INTEGER) ELSE updated_at_ms END,
            started_at = CAST(started_at * 1000 AS INTEGER),
            completed_at = CASE WHEN completed_at IS NULL THEN NULL ELSE CAST(completed_at * 1000 AS INTEGER) END
        WHERE created_at_ms = 0 OR updated_at_ms = 0 OR goal IS NULL
    """)

    schema_statements = """
        CREATE TABLE IF NOT EXISTS projects (
            id TEXT PRIMARY KEY,
            canonical_path TEXT NOT NULL UNIQUE,
            display_name TEXT NOT NULL,
            git_metadata_json TEXT NOT NULL DEFAULT '{}',
            lock_session_id TEXT UNIQUE REFERENCES sessions(id),
            lock_acquired_at_ms INTEGER,
            created_at_ms INTEGER NOT NULL CHECK (created_at_ms >= 0),
            updated_at_ms INTEGER NOT NULL CHECK (updated_at_ms >= 0)
        );

        CREATE TABLE IF NOT EXISTS agent_definitions (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            kind TEXT NOT NULL,
            base_role TEXT,
            template_version TEXT,
            definition_json TEXT NOT NULL,
            created_at_ms INTEGER NOT NULL CHECK (created_at_ms >= 0),
            updated_at_ms INTEGER NOT NULL CHECK (updated_at_ms >= 0),
            UNIQUE(name, template_version)
        );

        CREATE TABLE IF NOT EXISTS skills (
            id TEXT PRIMARY KEY,
            manifest_json TEXT NOT NULL,
            content_hash TEXT NOT NULL UNIQUE,
            trust_state TEXT NOT NULL,
            source_path TEXT NOT NULL UNIQUE,
            enabled INTEGER NOT NULL DEFAULT 0 CHECK (enabled IN (0, 1)),
            created_at_ms INTEGER NOT NULL CHECK (created_at_ms >= 0),
            updated_at_ms INTEGER NOT NULL CHECK (updated_at_ms >= 0)
        );

        CREATE TABLE IF NOT EXISTS provider_profiles (
            id TEXT PRIMARY KEY,
            provider_kind TEXT NOT NULL,
            display_name TEXT NOT NULL,
            endpoint TEXT,
            credential_reference TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at_ms INTEGER NOT NULL CHECK (created_at_ms >= 0),
            updated_at_ms INTEGER NOT NULL CHECK (updated_at_ms >= 0)
        );

        CREATE TABLE IF NOT EXISTS session_agents (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL REFERENCES sessions(id),
            agent_definition_id TEXT REFERENCES agent_definitions(id),
            role TEXT NOT NULL,
            snapshot_json TEXT NOT NULL,
            model_snapshot_json TEXT NOT NULL DEFAULT '{}',
            skill_snapshot_json TEXT NOT NULL DEFAULT '[]',
            created_at_ms INTEGER NOT NULL CHECK (created_at_ms >= 0),
            UNIQUE(session_id, id)
        );

        CREATE TABLE IF NOT EXISTS session_configurations (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL REFERENCES sessions(id),
            version INTEGER NOT NULL CHECK (version >= 1),
            available_agent_ids_json TEXT NOT NULL,
            required_role_rules_json TEXT NOT NULL,
            execution_limits_json TEXT NOT NULL,
            approval_behavior_json TEXT NOT NULL,
            acknowledgements_json TEXT NOT NULL DEFAULT '[]',
            policy_hash TEXT NOT NULL,
            created_at_ms INTEGER NOT NULL CHECK (created_at_ms >= 0),
            UNIQUE(session_id, version),
            UNIQUE(session_id, policy_hash)
        );

        CREATE TABLE IF NOT EXISTS events (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL REFERENCES sessions(id),
            sequence INTEGER NOT NULL CHECK (sequence >= 0),
            event_type TEXT NOT NULL,
            actor_id TEXT NOT NULL,
            correlation_id TEXT,
            command_id TEXT,
            payload_json TEXT NOT NULL,
            timestamp_ms INTEGER NOT NULL CHECK (timestamp_ms >= 0),
            created_at_ms INTEGER NOT NULL CHECK (created_at_ms >= 0),
            UNIQUE(session_id, sequence),
            UNIQUE(session_id, command_id)
        );

        CREATE TABLE IF NOT EXISTS assignments (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL REFERENCES sessions(id),
            parent_id TEXT REFERENCES assignments(id),
            assignee_session_agent_id TEXT NOT NULL REFERENCES session_agents(id),
            state TEXT NOT NULL,
            operation_class TEXT NOT NULL,
            acceptance_criteria_json TEXT NOT NULL,
            budget_json TEXT NOT NULL,
            configuration_version INTEGER NOT NULL,
            writer_lease_id TEXT,
            created_event_id TEXT NOT NULL REFERENCES events(id),
            terminal_event_id TEXT REFERENCES events(id),
            created_at_ms INTEGER NOT NULL CHECK (created_at_ms >= 0),
            updated_at_ms INTEGER NOT NULL CHECK (updated_at_ms >= 0)
        );

        CREATE TABLE IF NOT EXISTS assignment_attempts (
            id TEXT PRIMARY KEY,
            assignment_id TEXT NOT NULL REFERENCES assignments(id),
            attempt_number INTEGER NOT NULL CHECK (attempt_number >= 1),
            configuration_version INTEGER NOT NULL,
            checkpoint_json TEXT NOT NULL DEFAULT '{}',
            usage_json TEXT NOT NULL DEFAULT '{}',
            normalized_outcome_json TEXT NOT NULL DEFAULT '{}',
            failure_fingerprint TEXT,
            started_at_ms INTEGER NOT NULL CHECK (started_at_ms >= 0),
            completed_at_ms INTEGER,
            UNIQUE(assignment_id, attempt_number)
        );

        CREATE TABLE IF NOT EXISTS artifacts (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL REFERENCES sessions(id),
            assignment_id TEXT REFERENCES assignments(id),
            kind TEXT NOT NULL,
            relative_path TEXT,
            checksum TEXT NOT NULL,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at_ms INTEGER NOT NULL CHECK (created_at_ms >= 0),
            UNIQUE(session_id, checksum, kind)
        );

        CREATE TABLE IF NOT EXISTS gate_evidence (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL REFERENCES sessions(id),
            rule_id TEXT NOT NULL,
            assignment_id TEXT NOT NULL REFERENCES assignments(id),
            evidence_kind TEXT NOT NULL,
            validation_state TEXT NOT NULL,
            workspace_revision TEXT,
            artifact_ids_json TEXT NOT NULL DEFAULT '[]',
            created_at_ms INTEGER NOT NULL CHECK (created_at_ms >= 0),
            invalidated_at_ms INTEGER
        );

        CREATE TABLE IF NOT EXISTS limit_counters (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL REFERENCES sessions(id),
            scope_type TEXT NOT NULL,
            scope_id TEXT NOT NULL,
            counter_kind TEXT NOT NULL,
            consumed_value INTEGER NOT NULL DEFAULT 0 CHECK (consumed_value >= 0),
            threshold_value INTEGER,
            warning_emitted INTEGER NOT NULL DEFAULT 0 CHECK (warning_emitted IN (0, 1)),
            last_event_id TEXT REFERENCES events(id),
            updated_at_ms INTEGER NOT NULL CHECK (updated_at_ms >= 0),
            UNIQUE(session_id, scope_type, scope_id, counter_kind)
        );

        CREATE TABLE IF NOT EXISTS approvals (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL REFERENCES sessions(id),
            assignment_id TEXT REFERENCES assignments(id),
            capability TEXT NOT NULL,
            scope_json TEXT NOT NULL,
            decision TEXT,
            grant_expires_at_ms INTEGER,
            resolver_id TEXT,
            requested_at_ms INTEGER NOT NULL CHECK (requested_at_ms >= 0),
            resolved_at_ms INTEGER,
            request_event_id TEXT NOT NULL REFERENCES events(id),
            resolution_event_id TEXT REFERENCES events(id)
        );

        CREATE TABLE IF NOT EXISTS tool_executions (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL REFERENCES sessions(id),
            assignment_id TEXT REFERENCES assignments(id),
            tool_name TEXT NOT NULL,
            operation_class TEXT NOT NULL,
            request_summary TEXT NOT NULL,
            result_summary TEXT,
            exit_state TEXT NOT NULL,
            duration_ms INTEGER,
            artifact_ids_json TEXT NOT NULL DEFAULT '[]',
            requested_event_id TEXT NOT NULL REFERENCES events(id),
            completed_event_id TEXT REFERENCES events(id),
            created_at_ms INTEGER NOT NULL CHECK (created_at_ms >= 0),
            updated_at_ms INTEGER NOT NULL CHECK (updated_at_ms >= 0)
        );

        CREATE INDEX IF NOT EXISTS idx_sessions_project_updated ON sessions(project_id, updated_at_ms DESC);
        CREATE INDEX IF NOT EXISTS idx_events_session_sequence ON events(session_id, sequence);
        CREATE INDEX IF NOT EXISTS idx_events_session_created ON events(session_id, created_at_ms);
        CREATE INDEX IF NOT EXISTS idx_assignments_session_state ON assignments(session_id, state);
        CREATE INDEX IF NOT EXISTS idx_attempts_assignment ON assignment_attempts(assignment_id, attempt_number);
        CREATE INDEX IF NOT EXISTS idx_artifacts_session_created ON artifacts(session_id, created_at_ms DESC);
        CREATE INDEX IF NOT EXISTS idx_gate_evidence_session_rule ON gate_evidence(session_id, rule_id);
        CREATE INDEX IF NOT EXISTS idx_approvals_session_decision ON approvals(session_id, decision);
        CREATE INDEX IF NOT EXISTS idx_tool_executions_assignment ON tool_executions(assignment_id, created_at_ms);
    """
    # sqlite3.executescript() commits before executing; individual statements
    # preserve the migration runner's rollback guarantee on interruption.
    for statement in schema_statements.split(";"):
        if statement.strip():
            await db.execute(statement)
