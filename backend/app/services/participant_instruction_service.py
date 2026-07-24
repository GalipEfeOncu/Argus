"""Durable routing of human messages into scheduler-visible instructions."""

from __future__ import annotations

from dataclasses import dataclass
import uuid

import aiosqlite

from app.db.repositories import _now_ms
from app.services.session_configuration_service import ConfigurationError, SessionConfigurationService


@dataclass(frozen=True)
class ParticipantInstruction:
    id: str
    participant_id: str
    delivery_kind: str
    state: str


class ParticipantInstructionService:
    """Maps default messages to Coordinator and explicit mentions to participants.

    The human message remains the visible timeline record.  This compact table
    gives the scheduler a durable, queryable routing fact without duplicating
    user content or inventing hidden messages.
    """

    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    async def record_message(
        self, session_id: str, message_event_id: str, mention_ids: list[str],
    ) -> tuple[ParticipantInstruction, ...]:
        targets = await self._resolve_targets(session_id, mention_ids)
        now = _now_ms()
        result: list[ParticipantInstruction] = []
        for participant_id, delivery_kind in targets:
            instruction = ParticipantInstruction(str(uuid.uuid4()), participant_id, delivery_kind, "pending")
            await self._db.execute(
                """INSERT INTO participant_instructions
                   (id, session_id, message_event_id, participant_id, delivery_kind, state, created_at_ms)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (instruction.id, session_id, message_event_id, participant_id, delivery_kind, instruction.state, now),
            )
            result.append(instruction)
        return tuple(result)

    async def supersede_pending(self, session_id: str, participant_id: str) -> int:
        cursor = await self._db.execute(
            """UPDATE participant_instructions SET state = 'superseded', superseded_at_ms = ?
               WHERE session_id = ? AND participant_id = ? AND state = 'pending'""",
            (_now_ms(), session_id, participant_id),
        )
        return cursor.rowcount

    async def pending_for(self, session_id: str, participant_id: str) -> tuple[ParticipantInstruction, ...]:
        async with self._db.execute(
            """SELECT id, participant_id, delivery_kind, state FROM participant_instructions
               WHERE session_id = ? AND participant_id = ? AND state = 'pending' ORDER BY created_at_ms, id""",
            (session_id, participant_id),
        ) as cursor:
            rows = await cursor.fetchall()
        return tuple(ParticipantInstruction(row["id"], row["participant_id"], row["delivery_kind"], row["state"]) for row in rows)

    async def _resolve_targets(self, session_id: str, mention_ids: list[str]) -> tuple[tuple[str, str], ...]:
        try:
            snapshot = await SessionConfigurationService(self._db).current(session_id)
        except ConfigurationError:
            # Transitional sessions have no immutable participants yet; their
            # default human message still belongs to the visible Coordinator.
            # An explicit mention cannot safely target an unsnapshotted agent.
            if mention_ids:
                raise ConfigurationError("unknown_or_ambiguous_mention", "Explicit mentions require immutable session participants.")
            return (("coordinator", "coordinator"),)

        coordinator = next((agent["id"] for agent in snapshot.agent_snapshots if agent["role"] == "coordinator"), "coordinator")
        if not mention_ids:
            return ((coordinator, "coordinator"),)

        by_reference: dict[str, list[str]] = {}
        for agent in snapshot.agent_snapshots:
            for reference in (agent["id"], agent["sourceAgentId"], agent["role"]):
                candidates = by_reference.setdefault(reference.lower(), [])
                if agent["id"] not in candidates:
                    candidates.append(agent["id"])
        targets: list[tuple[str, str]] = []
        for mention_id in dict.fromkeys(mention_ids):
            matches = by_reference.get(mention_id.lower(), [])
            if len(matches) != 1:
                raise ConfigurationError("unknown_or_ambiguous_mention", "Each mentioned participant must resolve to one session participant.")
            targets.append((matches[0], "explicit_mention"))
        return tuple(targets)
