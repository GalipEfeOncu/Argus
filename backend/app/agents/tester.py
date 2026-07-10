from langchain_core.messages import HumanMessage, SystemMessage
from .state import AgentState
from .base_agent import BaseAgent


TESTER_SYSTEM_PROMPT = """You are the Tester agent in a multi-agent software development team.
You verify that the implemented code works correctly.

Your responsibilities:
1. Run existing tests with shell_exec
2. Write new tests if needed
3. Verify the main functionality works as expected
4. Report test results clearly (passed/failed, with details)

Always run tests from the project directory."""


class TesterAgent(BaseAgent):
    role = "tester"
    system_prompt = TESTER_SYSTEM_PROMPT

    async def run(self, state: AgentState) -> dict:
        messages = [
            SystemMessage(content=self.system_prompt),
            HumanMessage(
                content=(
                    f"Task: {state['current_task']}\n\n"
                    f"Project path: {state['project_path']}\n\n"
                    f"The code has been reviewed and approved. Please run tests."
                )
            ),
        ]
        response = await self.llm_with_tools.ainvoke(messages)
        return {
            "messages": [response],
            "active_agent": "done",
        }


def create_tester_node(provider_type: str, model_id: str, api_key: str, base_url: str | None = None, tools=None):
    agent = TesterAgent(provider_type, model_id, api_key, base_url, tools=tools)
    async def node(state: AgentState) -> dict:
        return await agent.run(state)
    return node
