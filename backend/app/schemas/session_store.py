"""Typed bounded read models for the canonical event-store REST resources."""

from app.schemas.session_events import ArgusSessionEvent, CamelModel, Identifier


class TimelinePageResponse(CamelModel):
    events: list[ArgusSessionEvent]
    next_after_sequence: int | None = None


class ArtifactSummaryResponse(CamelModel):
    id: Identifier
    kind: Identifier
    relative_path: str | None = None
    checksum: Identifier
    metadata: dict[str, object]
    created_at_ms: int


class ArtifactPageResponse(CamelModel):
    items: list[ArtifactSummaryResponse]
    next_cursor: str | None = None
