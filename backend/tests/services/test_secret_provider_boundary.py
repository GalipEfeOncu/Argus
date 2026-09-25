"""Synthetic-secret regression at the specialist/provider handoff."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from app.config import settings
from app.db.database import get_db, transaction
from app.db.repositories import SessionRepository
from app.providers.protocol import StructuredOutput, ToolCall
from app.providers.scripted import ScriptedProvider
from app.schemas.project import WorkspaceMode
from app.schemas.provider import ProviderProfileCreate
from app.schemas.session import SessionAgentInput, SessionConfigurationInput
from app.schemas.session_commands import parse_session_command
from app.services.command_processor import CommandProcessor
from app.services.provider_profile_service import ProviderProfileService
from app.services.session_configuration_service import SessionConfigurationService
from app.services.session_runtime_manager import SessionRuntimeManager
from app.services.workspace_service import ProjectWorkspaceService


@pytest.mark.asyncio
@pytest.mark.parametrize(("tool_name", "path", "returns_result"), [
    ("read_file", "nested/.env.production", False),
    ("read_file", "nested/settings.json", False),
    ("search_files", ".", True),
])
async def test_nested_fake_secrets_never_enter_specialist_provider_followup(
    temporary_sqlite_db, tmp_path: Path, tool_name: str, path: str, returns_result: bool,
) -> None:
    database = await get_db()
    profile = await ProviderProfileService(database).create(ProviderProfileCreate(
        providerKind="openai", displayName="Configured provider",
    ))
    await SessionRepository(database).create_legacy_session(
        session_id="secret-boundary", name="Secret boundary", project_path="workspace",
        task="Inspect the project.", role_configs=[],
    )
    async with transaction(database):
        snapshot = await SessionConfigurationService(database).create_initial(
            session_id="secret-boundary",
            agents=[
                SessionAgentInput.model_validate({
                    "id": "coordinator", "role": "coordinator",
                    "systemPrompt": "Return one bounded Coordinator action.",
                    "modelBinding": {"providerProfileId": profile.id, "modelId": "configured-model"},
                }),
                SessionAgentInput.model_validate({
                    "id": "builder", "role": "builder", "capabilities": ["workspace.read"],
                    "toolAllowlist": ["read_file", "search_files"],
                    "modelBinding": {"providerProfileId": profile.id, "modelId": "configured-model"},
                }),
            ],
            coordinator_id="coordinator",
            configuration=SessionConfigurationInput.model_validate({"availableAgentIds": ["builder"]}),
            workspace_mode="snapshot", acknowledged_direct_write=False,
        )
    builder_id = snapshot.available_agent_ids[0]
    source = tmp_path / "source"
    nested = source / "nested"
    nested.mkdir(parents=True)
    fake_secret = "example-provider-secret-12345"
    (nested / ".env.production").write_text(f"API_TOKEN={fake_secret}\n", encoding="utf-8")
    (nested / "settings.json").write_text(
        f'{{"ordinary": "visible", "api_key": "{fake_secret}"}}\n', encoding="utf-8",
    )
    (nested / "safe.txt").write_text("visible-evidence\n", encoding="utf-8")
    workspaces = ProjectWorkspaceService(database, managed_root=Path(settings.db_path).resolve().parent / "workspaces")
    project = await workspaces.register_project(str(source))
    await workspaces.prepare_workspace(session_id="secret-boundary", project_id=str(project["id"]), mode=WorkspaceMode.snapshot)
    coordinator = ScriptedProvider(((StructuredOutput({
        "type": "assignments", "routingSummary": "Inspect the workspace.",
        "assignments": [{
            "proposalId": "secret-probe", "assigneeAgentId": builder_id,
            "objective": "Find visible evidence.", "acceptanceCriteria": ["Report evidence."],
            "operationClass": "read_only", "requestedBudget": {},
            "requestedCapabilities": ["workspace.read"], "requestedTools": [tool_name],
            "reasonSummary": "The configured specialist can inspect the workspace.",
        }],
    }),),))
    arguments = {"path": path} if tool_name == "read_file" else {"query": "visible-evidence", "path": path}
    specialist = ScriptedProvider((
        (ToolCall("secret-call", tool_name, arguments),),
        (StructuredOutput({"summary": "Safe evidence was found.", "evidence": []}),),
    ))
    follow_up = ScriptedProvider(((StructuredOutput({
        "type": "final", "finalSummary": "Safe evidence was found.", "evidenceReferences": ["secret-probe"],
    }),),))
    providers = iter((coordinator, specialist, follow_up))

    async def resolver(_profile_id: str, _model_id: str):
        return next(providers)

    manager = SessionRuntimeManager(provider_resolver=resolver, publisher=lambda _session, _events: asyncio.sleep(0))
    try:
        await CommandProcessor(database).process("secret-boundary", parse_session_command({
            "commandId": "start-secret-boundary", "type": "session.start", "payload": {},
        }))
        await manager.start("secret-boundary")
        await manager.wait("secret-boundary")
        requests = specialist.requests
    finally:
        await manager.shutdown()
        await database.close()

    assert len(requests) == (2 if returns_result else 1)
    assert fake_secret not in json.dumps([request.messages for request in requests])
    if returns_result:
        assert "nested/safe.txt:1:visible-evidence" in requests[1].messages[-1]["content"]
