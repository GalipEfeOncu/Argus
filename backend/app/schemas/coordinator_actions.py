"""Strict, tool-free Coordinator action contract for the dynamic runtime."""

from __future__ import annotations

from typing import Annotated, Any, Literal, Union

from pydantic import Field, TypeAdapter

from app.schemas.session_events import CamelModel, Identifier, Summary


ConciseSummary = Annotated[str, Field(min_length=1, max_length=800)]


class CoordinatorAssignment(CamelModel):
    proposal_id: Identifier
    assignee_agent_id: Identifier
    parent_id: Identifier | None = None
    objective: Summary
    acceptance_criteria: list[Summary] = Field(min_length=1, max_length=20)
    operation_class: Literal["read_only", "mutating"]
    requested_budget: dict[str, int | float | None] = Field(max_length=20)
    requested_capabilities: list[Identifier] = Field(default_factory=list, max_length=20)
    reason_summary: ConciseSummary


class AssignmentsAction(CamelModel):
    type: Literal["assignments"]
    routing_summary: ConciseSummary
    assignments: list[CoordinatorAssignment] = Field(min_length=1, max_length=8)


class WaitAction(CamelModel):
    type: Literal["wait"]
    routing_summary: ConciseSummary


class AskUserAction(CamelModel):
    type: Literal["ask_user"]
    routing_summary: ConciseSummary
    question: ConciseSummary


class FinalAction(CamelModel):
    type: Literal["final"]
    final_summary: ConciseSummary
    evidence_references: list[Identifier] = Field(min_length=1, max_length=50)


class PartialAction(CamelModel):
    type: Literal["partial"]
    final_summary: ConciseSummary
    unmet_requirements: list[ConciseSummary] = Field(min_length=1, max_length=50)
    evidence_references: list[Identifier] = Field(default_factory=list, max_length=50)


class StopAction(CamelModel):
    type: Literal["stop"]
    final_summary: ConciseSummary
    reason: ConciseSummary


CoordinatorAction = Annotated[
    Union[AssignmentsAction, WaitAction, AskUserAction, FinalAction, PartialAction, StopAction],
    Field(discriminator="type"),
]

COORDINATOR_ACTION_ADAPTER = TypeAdapter(CoordinatorAction)


def parse_coordinator_action(value: Any) -> CoordinatorAction:
    """Validate a provider's untrusted structured Coordinator response."""

    return COORDINATOR_ACTION_ADAPTER.validate_python(value)


def coordinator_action_schema() -> dict[str, Any]:
    return COORDINATOR_ACTION_ADAPTER.json_schema()
