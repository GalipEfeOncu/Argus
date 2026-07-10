from langchain_core.messages import HumanMessage, SystemMessage
from .state import AgentState
from .base_agent import BaseAgent


BUILDER_SYSTEM_PROMPT = """You are the Builder agent in a multi-agent software development team.
You receive a plan from the Planner and implement it by writing code.

Your responsibilities:
1. Read relevant existing files using read_file tool
2. Write or modify files using write_file or edit_file tools
3. Run shell commands to install dependencies if needed (shell_exec)
4. Report what changes you made clearly

Be precise with file paths. Always read a file before modifying it.
Explain each change you make in your response."""


class BuilderAgent(BaseAgent):
    role = "builder"
    system_prompt = BUILDER_SYSTEM_PROMPT

    async def run(self, state: AgentState) -> dict:
        human_feedback = state.get("human_feedback")
        feedback_part = f"\n\nHuman feedback: {human_feedback}" if human_feedback else ""

        messages = [
            SystemMessage(content=self.system_prompt),
            HumanMessage(
                content=(
                    f"Task: {state['current_task']}\n\n"
                    f"Plan:\n{state.get('plan', 'No plan provided.')}\n\n"
                    f"Project path: {state['project_path']}"
                    f"{feedback_part}"
                )
            ),
        ]
        response = await self.llm_with_tools.ainvoke(messages)
        return {
            "messages": [response],
            "active_agent": "reviewer",
            "human_feedback": None,  # Clear after use
            "iteration_count": state.get("iteration_count", 0) + 1,
        }


def create_builder_node(provider_type: str, model_id: str, api_key: str, base_url: str | None = None, tools=None):
    agent = BuilderAgent(provider_type, model_id, api_key, base_url, tools=tools)
    async def node(state: AgentState) -> dict:
        return await agent.run(state)
    return node
