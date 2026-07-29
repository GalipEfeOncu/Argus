"""Immutable agent-definition catalogue and session-snapshot resolver."""

from __future__ import annotations

from dataclasses import dataclass
import json
import uuid

import aiosqlite

from app.db.database import transaction
from app.db.repositories import _now_ms, _safe_json
from app.schemas.session import AgentDefinitionCreate, AgentDefinitionResponse, SessionAgentInput
from app.services.evidence_schema import is_supported_json_schema
from app.services.session_configuration_service import ConfigurationError


_BUILTIN_DEFINITIONS: tuple[dict[str, object], ...] = (
    {
        "id": "builtin.coordinator.v1", "name": "Coordinator", "kind": "builtin", "baseRole": "coordinator",
        "role": "coordinator", "templateVersion": "1.0.0", "systemPrompt": "Coordinate bounded work and explain routing in the shared room.",
        "modelBinding": {"providerProfileId": "builtin", "modelId": "provider-neutral"}, "skillIds": [],
        "toolAllowlist": [], "capabilities": [], "permissionProfile": "balanced", "evidenceKinds": [], "outputLanguage": "en",
    },
    {
        "id": "builtin.planner.v1", "name": "Planner", "kind": "builtin", "baseRole": "planner",
        "role": "planner", "templateVersion": "1.0.0", "systemPrompt": "Create concise, verifiable plans before implementation.",
        "modelBinding": {"providerProfileId": "builtin", "modelId": "provider-neutral"}, "skillIds": [],
        "toolAllowlist": ["read_file", "search_files"], "capabilities": ["workspace.read"], "permissionProfile": "balanced",
        "evidenceKinds": ["accepted_plan"], "outputLanguage": "en",
    },
    {
        "id": "builtin.builder.v1", "name": "Builder", "kind": "builtin", "baseRole": "builder",
        "role": "builder", "templateVersion": "1.0.0", "systemPrompt": "Implement only the bounded assignment and report verifiable results.",
        "modelBinding": {"providerProfileId": "builtin", "modelId": "provider-neutral"}, "skillIds": [],
        "toolAllowlist": ["read_file", "write_file", "edit_file", "search_files", "shell_exec", "git_diff"],
        "capabilities": ["workspace.read", "workspace.write", "test.run"], "permissionProfile": "balanced",
        "evidenceKinds": ["verified_change"], "outputLanguage": "en",
    },
    {
        "id": "builtin.reviewer.v1", "name": "Reviewer", "kind": "builtin", "baseRole": "reviewer",
        "role": "reviewer", "templateVersion": "1.0.0", "systemPrompt": "Review changes against the acceptance criteria and provide structured findings.",
        "modelBinding": {"providerProfileId": "builtin", "modelId": "provider-neutral"}, "skillIds": [],
        "toolAllowlist": ["read_file", "search_files", "git_diff"], "capabilities": ["workspace.read"], "permissionProfile": "balanced",
        "evidenceKinds": ["approved_review"], "outputLanguage": "en",
    },
    {
        "id": "builtin.tester.v1", "name": "Tester", "kind": "builtin", "baseRole": "tester",
        "role": "tester", "templateVersion": "1.0.0", "systemPrompt": "Run relevant tests and report reproducible, structured results.",
        "modelBinding": {"providerProfileId": "builtin", "modelId": "provider-neutral"}, "skillIds": [],
        "toolAllowlist": ["read_file", "search_files", "shell_exec"], "capabilities": ["workspace.read", "test.run"], "permissionProfile": "balanced",
        "evidenceKinds": ["passing_test_run"], "outputLanguage": "en",
    },
    {
        "id": "builtin.ui_agent.v1", "name": "UI Agent", "kind": "builtin", "baseRole": "ui_agent",
        "role": "ui_agent", "templateVersion": "1.0.0", "systemPrompt": "Implement accessible interface changes within the requested scope.",
        "modelBinding": {"providerProfileId": "builtin", "modelId": "provider-neutral"}, "skillIds": [],
        "toolAllowlist": ["read_file", "write_file", "edit_file", "search_files", "git_diff"],
        "capabilities": ["workspace.read", "workspace.write"], "permissionProfile": "balanced",
        "evidenceKinds": ["verified_change"], "outputLanguage": "en",
    },
)
_PROFILE_RANK = {"strict": 0, "balanced": 1, "autonomous": 2, "expert_unrestricted": 3}
_BUILTIN_EVIDENCE = {
    "planner": "accepted_plan", "builder": "verified_change", "ui_agent": "verified_change",
    "reviewer": "approved_review", "tester": "passing_test_run",
}
_RESERVED_EVIDENCE_KINDS = frozenset(_BUILTIN_EVIDENCE.values())
_MAX_SESSION_SKILL_SNAPSHOT_BYTES = 4_000_000


@dataclass(frozen=True)
class StoredAgentDefinition:
    id: str
    value: dict[str, object]


class AgentDefinitionService:
    """Own the append-only definition catalogue; sessions only consume copies."""

    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    async def ensure_builtin_templates(self) -> None:
        now = _now_ms()
        async with transaction(self._db):
            for value in _BUILTIN_DEFINITIONS:
                await self._db.execute(
                    """INSERT OR IGNORE INTO agent_definitions
                       (id, name, kind, base_role, template_version, definition_json, created_at_ms, updated_at_ms)
                       VALUES (?, ?, 'builtin', ?, ?, ?, ?, ?)""",
                    (value["id"], value["name"], value["baseRole"], value["templateVersion"], _safe_json(value), now, now),
                )

    async def list(self) -> list[AgentDefinitionResponse]:
        await self.ensure_builtin_templates()
        async with self._db.execute(
            "SELECT id, definition_json, created_at_ms FROM agent_definitions ORDER BY kind = 'builtin' DESC, name, created_at_ms"
        ) as cursor:
            rows = await cursor.fetchall()
        return [self._response(row["id"], json.loads(row["definition_json"]), row["created_at_ms"]) for row in rows]

    async def get(self, definition_id: str) -> StoredAgentDefinition | None:
        await self.ensure_builtin_templates()
        async with self._db.execute("SELECT id, definition_json FROM agent_definitions WHERE id = ?", (definition_id,)) as cursor:
            row = await cursor.fetchone()
        return None if row is None else StoredAgentDefinition(str(row["id"]), json.loads(row["definition_json"]))

    async def create(self, definition: AgentDefinitionCreate) -> AgentDefinitionResponse:
        await self.ensure_builtin_templates()
        if definition.kind == "builtin":
            raise ConfigurationError("builtin_template_reserved", "Built-in templates are managed by the runtime.")
        if definition.kind == "builtin_override" and definition.base_role is None:
            raise ConfigurationError("base_role_required", "A built-in override must name its built-in base role.")
        if definition.kind == "custom" and definition.base_role is not None:
            raise ConfigurationError("custom_base_role_forbidden", "A custom role cannot claim a built-in base role.")
        if definition.kind == "custom" and not is_supported_json_schema(definition.evidence_schema):
            raise ConfigurationError("custom_evidence_schema_required", "A custom role requires a supported evidence schema.")
        if definition.kind == "custom" and not definition.evidence_kinds:
            raise ConfigurationError("custom_evidence_kind_required", "A custom role requires at least one declared evidence kind.")
        if definition.kind == "custom" and _RESERVED_EVIDENCE_KINDS.intersection(definition.evidence_kinds):
            raise ConfigurationError("reserved_evidence_kind", "Custom roles cannot replace built-in evidence validators.")
        if definition.kind == "builtin_override" and definition.base_role not in {item["role"] for item in _BUILTIN_DEFINITIONS}:
            raise ConfigurationError("unknown_builtin_role", "The override base role is not a built-in template.")
        if definition.kind == "builtin_override" and definition.role != definition.base_role:
            raise ConfigurationError("override_role_mismatch", "A built-in override keeps its base role identity.")
        if definition.kind == "builtin_override":
            expected_evidence = _BUILTIN_EVIDENCE[str(definition.base_role)]
            if definition.evidence_kinds != [expected_evidence] or definition.evidence_schema is not None:
                raise ConfigurationError("builtin_evidence_contract_immutable", "Built-in overrides retain their deterministic evidence contract.")
        definition_id = f"agd_{uuid.uuid4().hex}"
        async with self._db.execute("SELECT COUNT(*) AS total FROM agent_definitions WHERE name = ?", (definition.name,)) as cursor:
            version = int((await cursor.fetchone())["total"]) + 1
        value = definition.model_dump(by_alias=True, mode="json")
        value.update({"id": definition_id, "templateVersion": f"{version}.0.0"})
        now = _now_ms()
        async with transaction(self._db):
            await self._db.execute(
                """INSERT INTO agent_definitions
                   (id, name, kind, base_role, template_version, definition_json, created_at_ms, updated_at_ms)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (definition_id, definition.name, definition.kind, definition.base_role, value["templateVersion"], _safe_json(value), now, now),
            )
        return self._response(definition_id, value, now)

    async def resolve_session_agents(self, inputs: list[SessionAgentInput]) -> list[SessionAgentInput]:
        """Expand a durable definition before it crosses the immutable session boundary."""

        await self.ensure_builtin_templates()
        resolved: list[SessionAgentInput] = []
        total_skill_snapshot_bytes = 0
        for supplied in inputs:
            definition_id = supplied.agent_definition_id or f"builtin.{supplied.role}.v1"
            stored = await self.get(definition_id)
            if stored is None:
                raise ConfigurationError("agent_definition_not_found", "An agent definition was not found.")
            value = stored.value
            if supplied.role != value.get("role"):
                raise ConfigurationError("agent_role_mismatch", "The supplied role does not match its definition.")
            for field, label in (("capabilities", "capabilities"), ("tool_allowlist", "tool allowlist")):
                if field in supplied.model_fields_set and not set(getattr(supplied, field)).issubset(set(value[_camel(field)])):
                    raise ConfigurationError("agent_override_escalation", f"A session override cannot expand {label}.")
            if "permission_profile" in supplied.model_fields_set and _PROFILE_RANK[supplied.permission_profile] > _PROFILE_RANK[str(value["permissionProfile"])]:
                raise ConfigurationError("agent_override_escalation", "A session override cannot expand its permission profile.")
            if "evidence_schema" in supplied.model_fields_set and supplied.evidence_schema != value.get("evidenceSchema"):
                raise ConfigurationError("agent_evidence_contract_immutable", "Session overrides cannot replace the definition evidence contract.")
            assembled = {
                "id": supplied.id, "role": value["role"], "agentDefinitionId": stored.id,
                "definitionVersion": value["templateVersion"],
                "name": supplied.name if "name" in supplied.model_fields_set else value["name"],
                "systemPrompt": supplied.system_prompt if "system_prompt" in supplied.model_fields_set else value["systemPrompt"],
                "modelBinding": (supplied.model_binding.model_dump(by_alias=True, mode="json") if supplied.model_binding is not None else _legacy_model_binding(supplied.model_snapshot)) if ("model_binding" in supplied.model_fields_set or supplied.model_snapshot) else value["modelBinding"],
                "capabilities": supplied.capabilities if "capabilities" in supplied.model_fields_set else value["capabilities"],
                # Explicit session skill selection is allowed only after the
                # stored package proves it fits this agent below; unlike a
                # tool/capability override it cannot itself grant authority.
                "skillIds": supplied.skill_ids if "skill_ids" in supplied.model_fields_set else value["skillIds"],
                "toolAllowlist": supplied.tool_allowlist if "tool_allowlist" in supplied.model_fields_set else value["toolAllowlist"],
                "permissionProfile": supplied.permission_profile if "permission_profile" in supplied.model_fields_set else value["permissionProfile"],
                "evidenceSchema": value.get("evidenceSchema"), "evidenceKinds": value["evidenceKinds"],
                "outputLanguage": supplied.output_language if "output_language" in supplied.model_fields_set else value["outputLanguage"],
                "modelSnapshot": supplied.model_snapshot,
            }
            agent = SessionAgentInput.model_validate(assembled)
            # Caller-provided skill text is never trusted. Resolve the stored
            # immutable copy and enforce its declarations against this exact
            # agent snapshot before it can enter a session.
            from app.services.skill_package_service import SkillPackageService
            snapshots = await SkillPackageService(self._db).snapshots_for_agent(
                agent.skill_ids, tool_allowlist=agent.tool_allowlist, capabilities=agent.capabilities,
            )
            snapshot_size = len(_safe_json(snapshots).encode("utf-8"))
            total_skill_snapshot_bytes += snapshot_size
            if total_skill_snapshot_bytes > _MAX_SESSION_SKILL_SNAPSHOT_BYTES:
                raise ConfigurationError("skill_snapshot_too_large", "Enabled skill snapshots exceed the session context size limit.")
            resolved.append(agent.model_copy(update={"skill_snapshot": snapshots}))
        return resolved

    @staticmethod
    def _response(definition_id: str, value: dict[str, object], created_at_ms: int) -> AgentDefinitionResponse:
        return AgentDefinitionResponse.model_validate({**value, "id": definition_id, "createdAtMs": created_at_ms})


def _camel(field: str) -> str:
    return {"skill_ids": "skillIds", "tool_allowlist": "toolAllowlist"}.get(field, field)


def _legacy_model_binding(value: dict[str, object]) -> dict[str, object]:
    """Translate the transitional launcher naming without accepting secrets."""

    return {
        "providerProfileId": value.get("providerProfileId", value.get("providerId")),
        "modelId": value.get("modelId"),
    }
