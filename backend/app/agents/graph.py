from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver

from .state import AgentState
from .planner import create_planner_node
from .builder import create_builder_node
from .reviewer import create_reviewer_node
from .tester import create_tester_node
from .ui_agent import create_ui_agent_node
from .router import route_after_review
from app.config import settings


def build_agent_graph(
    session_id: str,
    role_configs: list[dict],
    tools: list | None = None,
):
    """
    Build a LangGraph StateGraph from the session's role configurations.
    Each role uses the model/provider the user assigned.
    """
    graph = StateGraph(AgentState)

    # Index configs by role
    config_by_role = {rc["role"]: rc for rc in role_configs if rc.get("enabled")}

    def get_llm_params(role: str) -> dict:
        rc = config_by_role.get(role, {})
        return {
            "provider_type": rc.get("provider_type", "openai_compat"),
            "model_id": rc.get("model_id", "gpt-4o-mini"),
            "api_key": rc.get("api_key", ""),
            "base_url": rc.get("base_url"),
        }

    # Add nodes for enabled roles
    has_planner = "planner" in config_by_role
    has_builder = "builder" in config_by_role
    has_reviewer = "reviewer" in config_by_role
    has_tester = "tester" in config_by_role
    has_ui_agent = "ui_agent" in config_by_role

    if has_planner:
        graph.add_node("planner", create_planner_node(**get_llm_params("planner")))
    if has_builder:
        graph.add_node("builder", create_builder_node(**get_llm_params("builder"), tools=tools))
    if has_reviewer:
        graph.add_node("reviewer", create_reviewer_node(**get_llm_params("reviewer"), tools=tools))
    if has_tester:
        graph.add_node("tester", create_tester_node(**get_llm_params("tester"), tools=tools))
    if has_ui_agent:
        graph.add_node("ui_agent", create_ui_agent_node(**get_llm_params("ui_agent"), tools=tools))

    # Wire edges
    if has_planner:
        graph.add_edge(START, "planner")
        if has_builder:
            graph.add_edge("planner", "builder")
        elif has_ui_agent:
            graph.add_edge("planner", "ui_agent")
    elif has_builder:
        graph.add_edge(START, "builder")

    if has_builder and has_reviewer:
        graph.add_edge("builder", "reviewer")
    elif has_builder:
        graph.add_edge("builder", END)

    if has_reviewer:
        graph.add_conditional_edges("reviewer", route_after_review, {
            "tester": "tester" if has_tester else END,
            "builder": "builder" if has_builder else END,
            "__end__": END,
        })

    if has_ui_agent and has_reviewer:
        graph.add_edge("ui_agent", "reviewer")
    elif has_ui_agent:
        graph.add_edge("ui_agent", END)

    if has_tester:
        graph.add_edge("tester", END)

    return graph


async def compile_graph(session_id: str, role_configs: list[dict], tools: list | None = None):
    """Compile the graph with in-memory checkpointing (MVP).
    For production, swap MemorySaver with AsyncSqliteSaver from langgraph-checkpoint-sqlite.
    """
    graph = build_agent_graph(session_id, role_configs, tools)
    checkpointer = MemorySaver()
    return graph.compile(checkpointer=checkpointer)
