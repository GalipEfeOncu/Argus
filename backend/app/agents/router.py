from .state import AgentState

MAX_ITERATIONS = 5


def route_after_review(state: AgentState) -> str:
    """Conditional edge after Reviewer node."""
    review_status = state.get("review_status")
    iteration_count = state.get("iteration_count", 0)

    if review_status == "approved":
        return "tester"
    elif review_status == "rejected":
        return "__end__"  # Rejected = stop
    else:
        # revision_needed — send back to builder
        # But cap iterations to prevent infinite loops
        if iteration_count >= MAX_ITERATIONS:
            return "__end__"
        return "builder"


def route_after_planner(state: AgentState) -> str:
    """Route after Planner based on task type."""
    task = state.get("current_task", "").lower()
    # If UI-related task and ui_agent is configured
    if any(kw in task for kw in ["ui", "css", "style", "component", "frontend"]):
        if state.get("has_ui_agent"):
            return "ui_agent"
    return "builder"
