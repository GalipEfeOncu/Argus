from fastapi import APIRouter

from app.schemas.session_events import event_schema

router = APIRouter()


@router.get("/session-events")
async def get_session_event_contract() -> dict:
    """Expose the versioned WebSocket event schema for local development tools."""
    return event_schema()
