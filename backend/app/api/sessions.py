import uuid
from datetime import datetime
from fastapi import APIRouter, HTTPException, Query
from app.schemas.session import SessionCreateRequest, SessionCreateResponse, SessionConfigurationResponse
from app.db.database import get_db
from app.db.repositories import EventRepository, SessionRepository
from app.schemas.session_store import ArtifactPageResponse, TimelinePageResponse
from app.services.command_processor import event_wire_value
from app.services.workspace_service import ProjectWorkspaceService, WorkspaceError
from app.schemas.project import WorkspaceMode
from app.config import settings
from pathlib import Path
from app.db.database import transaction
from app.services.session_configuration_service import ConfigurationError, SessionConfigurationService
from app.schemas.session import SessionAgentInput

router = APIRouter()


@router.post("/", response_model=SessionCreateResponse)
async def create_session(req: SessionCreateRequest):
    session_id = str(uuid.uuid4())
    name = req.name or f"Session {datetime.now().strftime('%m/%d %H:%M')}"
    goal = req.goal or req.task
    assert goal is not None

    db = await get_db()
    try:
        workspace_service = ProjectWorkspaceService(
            db, managed_root=Path(settings.db_path).expanduser().resolve().parent / "workspaces"
        )
        if req.project_id is not None:
            projects = [project for project in await workspace_service.list_projects() if project["id"] == req.project_id]
            if not projects:
                raise ConfigurationError("project_not_found", "The selected project is not registered.")
            project = projects[0]
        else:
            assert req.project_path is not None
            project = await workspace_service.register_project(req.project_path)
        configured_mode = req.configuration.workspace_policy.mode
        if req.workspace_mode is not None and configured_mode is not None and req.workspace_mode != configured_mode:
            raise ConfigurationError("workspace_mode_conflict", "workspaceMode must match configuration.workspacePolicy.mode.")
        mode = configured_mode or req.workspace_mode or (WorkspaceMode.worktree if project["gitMetadata"]["isGit"] else WorkspaceMode.snapshot)
        agents = list(req.agents) or SessionConfigurationService.legacy_agents(
            [role_config.model_dump(by_alias=True) for role_config in req.role_configs]
        )
        coordinator_id = req.coordinator_agent_id or next((agent.id for agent in agents if agent.role == "coordinator"), "coordinator")
        if not any(agent.id == coordinator_id for agent in agents):
            agents.append(SessionAgentInput(id=coordinator_id, role="coordinator"))
        # Validate before provisioning an isolated workspace so invalid input
        # never leaves a worktree/snapshot behind.
        SessionConfigurationService._validate(
            agents, coordinator_id, req.configuration, mode.value,
            acknowledged_direct_write=req.acknowledge_direct_write,
        )
        await SessionRepository(db).create_legacy_session(
            session_id=session_id, name=name, project_path=project["canonicalPath"], task=goal,
            role_configs=[role_config.model_dump() for role_config in req.role_configs],
            project_id=str(project["id"]),
        )
        try:
            workspace = await workspace_service.prepare_workspace(
                session_id=session_id, project_id=str(project["id"]), mode=mode,
                acknowledged_direct_write=req.acknowledge_direct_write,
            )
        except BaseException:
            await SessionRepository(db).discard_unstarted_session(session_id)
            raise
        await SessionRepository(db).set_workspace_path(session_id, str(workspace.root_path))
        try:
            async with transaction(db):
                snapshot = await SessionConfigurationService(db).create_initial(
                    session_id=session_id, agents=agents, coordinator_id=coordinator_id,
                    configuration=req.configuration, workspace_mode=mode.value,
                    acknowledged_direct_write=req.acknowledge_direct_write,
                )
        except BaseException:
            # Provisioning is all-or-nothing: a failed immutable snapshot must
            # not strand a managed workspace or worktree.
            try:
                await workspace_service.cleanup_workspace(session_id)
            finally:
                await SessionRepository(db).discard_unstarted_session(session_id)
            raise
    except ConfigurationError as error:
        await SessionRepository(db).discard_unstarted_session(session_id)
        raise HTTPException(422, {"code": error.code, "message": str(error)}) from error
    except (WorkspaceError, OSError) as error:
        raise HTTPException(422, {"code": "workspace_setup_failed", "message": str(error)}) from error
    finally:
        await db.close()

    return {"id": session_id, "name": name, "projectId": project["id"], "goal": goal, **snapshot.wire_value()}


@router.get("/")
async def list_sessions():
    db = await get_db()
    try:
        return await SessionRepository(db).list_legacy_sessions()
    finally:
        await db.close()


@router.get("/{session_id}")
async def get_session(session_id: str):
    db = await get_db()
    try:
        row = await SessionRepository(db).get_legacy_session(session_id)
    finally:
        await db.close()
    if not row:
        raise HTTPException(404, "Session not found")
    return dict(row)


@router.get("/{session_id}/configuration", response_model=SessionConfigurationResponse)
async def get_session_configuration(session_id: str):
    """Return the latest immutable normalized configuration snapshot."""

    db = await get_db()
    try:
        if await SessionRepository(db).get_legacy_session(session_id) is None:
            raise HTTPException(404, "Session not found")
        snapshot = await SessionConfigurationService(db).current(session_id)
        return snapshot.wire_value()
    except ConfigurationError as error:
        raise HTTPException(404, {"code": error.code, "message": str(error)}) from error
    finally:
        await db.close()


@router.get("/{session_id}/timeline", response_model=TimelinePageResponse)
async def get_timeline_page(
    session_id: str,
    after_sequence: int = Query(default=-1, ge=-1),
    limit: int = Query(default=100, ge=1, le=200),
):
    """Return one indexed timeline page; never hydrate the full event log."""

    db = await get_db()
    try:
        page = await EventRepository(db).page_after(session_id, after_sequence=after_sequence, limit=limit)
    finally:
        await db.close()
    return {
        "events": [event_wire_value(event) for event in page.events],
        "nextAfterSequence": page.next_after_sequence,
    }


@router.get("/{session_id}/artifacts", response_model=ArtifactPageResponse)
async def get_artifact_summaries(
    session_id: str,
    cursor: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
):
    """Return bounded artifact metadata using a stable created-at/id cursor."""

    before: tuple[int, str] | None = None
    if cursor is not None:
        timestamp, separator, artifact_id = cursor.partition(":")
        if not separator or not artifact_id:
            raise HTTPException(422, "Invalid artifact cursor")
        try:
            before = (int(timestamp), artifact_id)
        except ValueError as error:
            raise HTTPException(422, "Invalid artifact cursor") from error
    db = await get_db()
    try:
        page = await EventRepository(db).page_artifact_summaries(session_id, before=before, limit=limit)
    finally:
        await db.close()
    next_cursor = None if page.next_cursor is None else f"{page.next_cursor[0]}:{page.next_cursor[1]}"
    return {"items": list(page.items), "nextCursor": next_cursor}


@router.delete("/{session_id}")
async def delete_session(session_id: str):
    raise HTTPException(405, "Session deletion requires a future retention-policy workflow")
