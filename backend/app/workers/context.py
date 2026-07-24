"""Bounded assignment context construction with safe audit metadata."""

from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
import json
import logging
import re
from typing import Literal


_SENSITIVE_VALUE = re.compile(
    r"(?:sk-[A-Za-z0-9_-]{12,}|Bearer\s+\S+|AIza[\w-]{20,}|"
    r"gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|xox[baprs]-[A-Za-z0-9-]{12,}|"
    r"AKIA[0-9A-Z]{16}|eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]+\.)",
    re.I,
)
_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class AgentSnapshot:
    agent_id: str
    role: str
    system_prompt: str
    enabled_skills: tuple[str, ...] = ()
    tool_allowlist: tuple[str, ...] = ()
    output_language: str | None = None
    model_id: str | None = None


@dataclass(frozen=True)
class AssignmentContext:
    assignment_id: str
    acceptance_criteria: str
    parent_message: str | None = None
    handoff: str | None = None


@dataclass(frozen=True)
class TimelineContextItem:
    event_id: str
    kind: Literal["human_instruction", "message", "tool_summary", "artifact_summary"]
    summary: str
    unresolved: bool = False


@dataclass(frozen=True)
class ArtifactReference:
    artifact_id: str
    kind: str
    checksum: str
    relative_path: str | None = None


@dataclass(frozen=True)
class ContextSelectionMetadata:
    """Persistable selection information; deliberately contains no selected text."""

    selected_event_ids: tuple[str, ...]
    selected_artifact_ids: tuple[str, ...]
    included_sections: tuple[str, ...]
    truncated_sections: tuple[str, ...]
    character_count: int
    selection_fingerprint: str

    def persistence_value(self) -> dict[str, object]:
        """The only context data safe to write to the assignment-attempt record."""

        return {
            "selectedEventIds": list(self.selected_event_ids),
            "selectedArtifactIds": list(self.selected_artifact_ids),
            "includedSections": list(self.included_sections),
            "truncatedSections": list(self.truncated_sections),
            "characterCount": self.character_count,
            "selectionFingerprint": self.selection_fingerprint,
        }


@dataclass(frozen=True)
class BuiltContext:
    system_prompt: str
    user_prompt: str
    metadata: ContextSelectionMetadata


@dataclass(frozen=True)
class ContextLimits:
    max_recent_events: int = 20
    max_unresolved_instructions: int = 10
    max_artifacts: int = 10
    max_characters: int = 24_000


class AssignmentContextBuilder:
    """Builds ordered, bounded context without retaining a raw transcript."""

    def __init__(self, limits: ContextLimits = ContextLimits()) -> None:
        self._limits = limits

    def build(
        self,
        *,
        agent: AgentSnapshot,
        goal: str,
        assignment: AssignmentContext,
        recent_events: tuple[TimelineContextItem, ...] = (),
        summary: str | None = None,
        artifacts: tuple[ArtifactReference, ...] = (),
        project_identity: str | None = None,
        workspace_policy: str | None = None,
    ) -> BuiltContext:
        safe_system_prompt = _redact(agent.system_prompt)
        system_prompt = safe_system_prompt[:self._limits.max_characters]
        sections: list[tuple[str, str]] = []
        truncated: list[str] = []
        event_ids: list[str] = []
        artifact_ids: list[str] = []

        if len(system_prompt) < len(safe_system_prompt):
            truncated.append("system_prompt")
        agent_description = (
            f"role {agent.role}; enabled skills {', '.join(agent.enabled_skills) or 'none'}; "
            f"tool allowlist {', '.join(agent.tool_allowlist) or 'none'}; "
            f"output language {agent.output_language or 'default'}; model {agent.model_id or 'default'}"
        )
        sections.append(("agent_snapshot", self._safe("Agent snapshot", agent_description)))
        sections.append(("goal", self._safe("Goal", goal)))
        if project_identity:
            sections.append(("project", self._safe("Project", project_identity)))
        if workspace_policy:
            sections.append(("workspace_policy", self._safe("Workspace policy", workspace_policy)))
        sections.append(("assignment", self._safe("Assignment acceptance criteria", assignment.acceptance_criteria)))
        if assignment.parent_message:
            sections.append(("parent_message", self._safe("Parent message", assignment.parent_message)))
        if assignment.handoff:
            sections.append(("handoff", self._safe("Handoff", assignment.handoff)))

        unresolved = [item for item in recent_events if item.kind == "human_instruction" and item.unresolved]
        for item in unresolved[-self._limits.max_unresolved_instructions:]:
            sections.append(("unresolved_instruction", self._safe("Unresolved human instruction", item.summary)))
            event_ids.append(item.event_id)
        if len(unresolved) > self._limits.max_unresolved_instructions:
            truncated.append("unresolved_instructions")

        for item in recent_events[-self._limits.max_recent_events:]:
            if item.event_id in event_ids:
                continue
            sections.append(("recent_event", self._safe(item.kind.replace("_", " ").title(), item.summary)))
            event_ids.append(item.event_id)
        if len(recent_events) > self._limits.max_recent_events:
            truncated.append("recent_events")

        if summary:
            sections.append(("durable_summary", self._safe("Durable session summary", summary)))

        for artifact in artifacts[:self._limits.max_artifacts]:
            reference = f"{artifact.kind} {artifact.artifact_id} checksum {artifact.checksum}"
            if artifact.relative_path:
                reference += f" path {artifact.relative_path}"
            sections.append(("artifact_reference", reference))
            artifact_ids.append(artifact.artifact_id)
        if len(artifacts) > self._limits.max_artifacts:
            truncated.append("artifact_references")

        user_prompt, included, clipped = self._bounded_prompt(
            sections, max_characters=max(0, self._limits.max_characters - len(system_prompt))
        )
        if clipped:
            truncated.append("character_budget")
        fingerprint = sha256(
            "\n".join([*event_ids, *artifact_ids, *included, *truncated]).encode("utf-8")
        ).hexdigest()
        context = BuiltContext(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            metadata=ContextSelectionMetadata(
                selected_event_ids=tuple(event_ids),
                selected_artifact_ids=tuple(artifact_ids),
                included_sections=tuple(included),
                truncated_sections=tuple(truncated),
                character_count=len(user_prompt) + len(system_prompt),
                selection_fingerprint=fingerprint,
            ),
        )
        log_context_selection(context.metadata)
        return context

    @staticmethod
    def _safe(label: str, text: str) -> str:
        return f"{label}: {_redact(text)}"

    def _bounded_prompt(self, sections: list[tuple[str, str]], *, max_characters: int) -> tuple[str, list[str], bool]:
        output: list[str] = []
        included: list[str] = []
        remaining = max_characters
        for name, section in sections:
            rendered = f"{section}\n"
            if len(rendered) <= remaining:
                output.append(rendered)
                included.append(name)
                remaining -= len(rendered)
                continue
            if remaining > 0:
                output.append(f"{rendered[: max(0, remaining - 1)]}…")
                included.append(name)
            return "\n".join(output).strip(), included, True
        return "\n".join(output).strip(), included, False


def log_context_selection(metadata: ContextSelectionMetadata) -> None:
    """Emit safe audit metadata without prompt content, credentials, or reasoning."""

    _LOGGER.info("worker_context_selected %s", json.dumps(
        metadata.persistence_value(), separators=(",", ":"), sort_keys=True
    ))


def _redact(text: str) -> str:
    return _SENSITIVE_VALUE.sub("[REDACTED]", text.strip())
