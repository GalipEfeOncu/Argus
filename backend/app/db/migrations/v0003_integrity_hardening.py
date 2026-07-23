"""Protect immutable events and prevent cross-session projection links."""

from __future__ import annotations

import aiosqlite


async def apply(db: aiosqlite.Connection) -> None:
    statements = (
        """CREATE TRIGGER events_are_immutable_update
        BEFORE UPDATE ON events
        BEGIN SELECT RAISE(ABORT, 'events are immutable'); END""",
        """CREATE TRIGGER events_are_immutable_delete
        BEFORE DELETE ON events
        BEGIN SELECT RAISE(ABORT, 'events are immutable'); END""",
        """CREATE TRIGGER session_configurations_are_immutable_update
        BEFORE UPDATE ON session_configurations
        BEGIN SELECT RAISE(ABORT, 'session configurations are immutable'); END""",
        """CREATE TRIGGER session_configurations_are_immutable_delete
        BEFORE DELETE ON session_configurations
        BEGIN SELECT RAISE(ABORT, 'session configurations are immutable'); END""",
        """CREATE TRIGGER session_agents_are_immutable_update
        BEFORE UPDATE ON session_agents
        BEGIN SELECT RAISE(ABORT, 'session agents are immutable'); END""",
        """CREATE TRIGGER session_agents_are_immutable_delete
        BEFORE DELETE ON session_agents
        BEGIN SELECT RAISE(ABORT, 'session agents are immutable'); END""",
        """CREATE TRIGGER assignments_same_session_insert
        BEFORE INSERT ON assignments
        WHEN (SELECT session_id FROM session_agents WHERE id = NEW.assignee_session_agent_id) != NEW.session_id
          OR (NEW.parent_id IS NOT NULL AND (SELECT session_id FROM assignments WHERE id = NEW.parent_id) != NEW.session_id)
          OR (SELECT session_id FROM events WHERE id = NEW.created_event_id) != NEW.session_id
          OR (NEW.terminal_event_id IS NOT NULL AND (SELECT session_id FROM events WHERE id = NEW.terminal_event_id) != NEW.session_id)
        BEGIN SELECT RAISE(ABORT, 'assignment references another session'); END""",
        """CREATE TRIGGER assignments_same_session_update
        BEFORE UPDATE OF session_id, parent_id, assignee_session_agent_id, created_event_id, terminal_event_id ON assignments
        WHEN (SELECT session_id FROM session_agents WHERE id = NEW.assignee_session_agent_id) != NEW.session_id
          OR (NEW.parent_id IS NOT NULL AND (SELECT session_id FROM assignments WHERE id = NEW.parent_id) != NEW.session_id)
          OR (SELECT session_id FROM events WHERE id = NEW.created_event_id) != NEW.session_id
          OR (NEW.terminal_event_id IS NOT NULL AND (SELECT session_id FROM events WHERE id = NEW.terminal_event_id) != NEW.session_id)
        BEGIN SELECT RAISE(ABORT, 'assignment references another session'); END""",
        """CREATE TRIGGER gate_evidence_same_session_insert
        BEFORE INSERT ON gate_evidence
        WHEN (SELECT session_id FROM assignments WHERE id = NEW.assignment_id) != NEW.session_id
        BEGIN SELECT RAISE(ABORT, 'gate evidence references another session'); END""",
        """CREATE TRIGGER gate_evidence_same_session_update
        BEFORE UPDATE OF session_id, assignment_id ON gate_evidence
        WHEN (SELECT session_id FROM assignments WHERE id = NEW.assignment_id) != NEW.session_id
        BEGIN SELECT RAISE(ABORT, 'gate evidence references another session'); END""",
        """CREATE TRIGGER approvals_same_session_insert
        BEFORE INSERT ON approvals
        WHEN (NEW.assignment_id IS NOT NULL AND (SELECT session_id FROM assignments WHERE id = NEW.assignment_id) != NEW.session_id)
          OR (SELECT session_id FROM events WHERE id = NEW.request_event_id) != NEW.session_id
          OR (NEW.resolution_event_id IS NOT NULL AND (SELECT session_id FROM events WHERE id = NEW.resolution_event_id) != NEW.session_id)
        BEGIN SELECT RAISE(ABORT, 'approval references another session'); END""",
        """CREATE TRIGGER approvals_same_session_update
        BEFORE UPDATE OF session_id, assignment_id, request_event_id, resolution_event_id ON approvals
        WHEN (NEW.assignment_id IS NOT NULL AND (SELECT session_id FROM assignments WHERE id = NEW.assignment_id) != NEW.session_id)
          OR (SELECT session_id FROM events WHERE id = NEW.request_event_id) != NEW.session_id
          OR (NEW.resolution_event_id IS NOT NULL AND (SELECT session_id FROM events WHERE id = NEW.resolution_event_id) != NEW.session_id)
        BEGIN SELECT RAISE(ABORT, 'approval references another session'); END""",
        """CREATE TRIGGER tool_executions_same_session_insert
        BEFORE INSERT ON tool_executions
        WHEN (NEW.assignment_id IS NOT NULL AND (SELECT session_id FROM assignments WHERE id = NEW.assignment_id) != NEW.session_id)
          OR (SELECT session_id FROM events WHERE id = NEW.requested_event_id) != NEW.session_id
          OR (NEW.completed_event_id IS NOT NULL AND (SELECT session_id FROM events WHERE id = NEW.completed_event_id) != NEW.session_id)
        BEGIN SELECT RAISE(ABORT, 'tool execution references another session'); END""",
        """CREATE TRIGGER tool_executions_same_session_update
        BEFORE UPDATE OF session_id, assignment_id, requested_event_id, completed_event_id ON tool_executions
        WHEN (NEW.assignment_id IS NOT NULL AND (SELECT session_id FROM assignments WHERE id = NEW.assignment_id) != NEW.session_id)
          OR (SELECT session_id FROM events WHERE id = NEW.requested_event_id) != NEW.session_id
          OR (NEW.completed_event_id IS NOT NULL AND (SELECT session_id FROM events WHERE id = NEW.completed_event_id) != NEW.session_id)
        BEGIN SELECT RAISE(ABORT, 'tool execution references another session'); END""",
        """CREATE TRIGGER artifacts_same_session_insert
        BEFORE INSERT ON artifacts
        WHEN NEW.assignment_id IS NOT NULL AND (SELECT session_id FROM assignments WHERE id = NEW.assignment_id) != NEW.session_id
        BEGIN SELECT RAISE(ABORT, 'artifact references another session'); END""",
        """CREATE TRIGGER artifacts_same_session_update
        BEFORE UPDATE OF session_id, assignment_id ON artifacts
        WHEN NEW.assignment_id IS NOT NULL AND (SELECT session_id FROM assignments WHERE id = NEW.assignment_id) != NEW.session_id
        BEGIN SELECT RAISE(ABORT, 'artifact references another session'); END""",
        """CREATE TRIGGER limit_counters_same_session_insert
        BEFORE INSERT ON limit_counters
        WHEN NEW.last_event_id IS NOT NULL AND (SELECT session_id FROM events WHERE id = NEW.last_event_id) != NEW.session_id
        BEGIN SELECT RAISE(ABORT, 'limit counter references another session'); END""",
        """CREATE TRIGGER limit_counters_same_session_update
        BEFORE UPDATE OF session_id, last_event_id ON limit_counters
        WHEN NEW.last_event_id IS NOT NULL AND (SELECT session_id FROM events WHERE id = NEW.last_event_id) != NEW.session_id
        BEGIN SELECT RAISE(ABORT, 'limit counter references another session'); END""",
    )
    for statement in statements:
        await db.execute(statement)
