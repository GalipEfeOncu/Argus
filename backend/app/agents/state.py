import operator
from typing import Annotated, TypedDict, Optional
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class CodeChange(TypedDict):
    file_path: str
    before: str
    after: str
    additions: int
    deletions: int


class TestResult(TypedDict):
    passed: bool
    output: str
    duration_ms: int


class ToolCallRecord(TypedDict):
    id: str
    tool: str
    args: dict
    result: str
    duration_ms: int


class AgentState(TypedDict):
    # Core conversation messages (append-only with add_messages reducer)
    messages: Annotated[list[BaseMessage], add_messages]

    # Task & plan
    current_task: str
    plan: Optional[str]

    # Code changes made by Builder/UI Agent (accumulates)
    code_changes: Annotated[list[CodeChange], operator.add]

    # Review decision from Reviewer
    review_status: Optional[str]  # "approved" | "rejected" | "revision_needed"
    review_feedback: Optional[str]

    # Test results from Tester (accumulates)
    test_results: Annotated[list[TestResult], operator.add]

    # Active agent tracking
    active_agent: str

    # Project context
    project_path: str
    files_context: dict[str, str]  # path -> content cache

    # Human feedback from interrupt
    human_feedback: Optional[str]
    human_approved: Optional[bool]

    # Tool calls log (accumulates)
    tool_calls_log: Annotated[list[ToolCallRecord], operator.add]

    # Session metadata
    session_id: str
    iteration_count: int  # builder/reviewer cycles
    max_iterations: int
