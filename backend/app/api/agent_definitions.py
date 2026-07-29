"""Versioned agent-definition catalogue endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from app.db.database import get_db
from app.schemas.session import AgentDefinitionCreate, AgentDefinitionResponse
from app.services.agent_definition_service import AgentDefinitionService
from app.services.session_configuration_service import ConfigurationError


router = APIRouter()


@router.get("/", response_model=list[AgentDefinitionResponse])
async def list_agent_definitions() -> list[AgentDefinitionResponse]:
    db = await get_db()
    try:
        return await AgentDefinitionService(db).list()
    finally:
        await db.close()


@router.get("/{definition_id}", response_model=AgentDefinitionResponse)
async def get_agent_definition(definition_id: str) -> AgentDefinitionResponse:
    db = await get_db()
    try:
        stored = await AgentDefinitionService(db).get(definition_id)
        if stored is None:
            raise HTTPException(404, {"code": "agent_definition_not_found", "message": "Agent definition was not found."})
        async with db.execute("SELECT created_at_ms FROM agent_definitions WHERE id = ?", (definition_id,)) as cursor:
            row = await cursor.fetchone()
        assert row is not None
        return AgentDefinitionService._response(stored.id, stored.value, row["created_at_ms"])
    finally:
        await db.close()


@router.post("/", response_model=AgentDefinitionResponse, status_code=status.HTTP_201_CREATED)
async def create_agent_definition(definition: AgentDefinitionCreate) -> AgentDefinitionResponse:
    db = await get_db()
    try:
        return await AgentDefinitionService(db).create(definition)
    except ConfigurationError as error:
        raise HTTPException(422, {"code": error.code, "message": str(error)}) from error
    finally:
        await db.close()
