from langchain_core.messages import HumanMessage, SystemMessage
from .state import AgentState
from .base_agent import BaseAgent


UI_AGENT_SYSTEM_PROMPT = """You are the UI Agent in a multi-agent software development team.
You specialize in frontend development: HTML, CSS, React, TypeScript, and UX design.

Your responsibilities:
1. Create and modify UI components
2. Write CSS with proper styling and animations
3. Ensure responsive and accessible design
4. Handle state management and data binding

Use the file tools to read/write frontend files."""


class UIAgent(BaseAgent):
    role = "ui_agent"
    system_prompt = UI_AGENT_SYSTEM_PROMPT

    async def run(self, state: AgentState) -> dict:
        messages = [
            SystemMessage(content=self.system_prompt),
            HumanMessage(
                content=(
                    f"Task: {state['current_task']}\n\n"
                    f"Plan:\n{state.get('plan', 'No plan provided.')}\n\n"
                    f"Project path: {state['project_path']}"
                )
            ),
        ]
        response = await self.llm_with_tools.ainvoke(messages)
        return {
            "messages": [response],
            "active_agent": "reviewer",
        }


def create_ui_agent_node(provider_type: str, model_id: str, api_key: str, base_url: str | None = None, tools=None):
    agent = UIAgent(provider_type, model_id, api_key, base_url, tools=tools)
    async def node(state: AgentState) -> dict:
        return await agent.run(state)
    return node
