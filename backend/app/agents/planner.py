from langchain_core.messages import HumanMessage, SystemMessage
from .state import AgentState
from .base_agent import BaseAgent


PLANNER_SYSTEM_PROMPT = """You are the Planner agent in a multi-agent software development team.
Your job is to analyze the given task and create a clear, step-by-step implementation plan.

Your plan should:
1. Break down the task into concrete, actionable steps
2. Identify which files need to be created or modified
3. Note any dependencies or potential pitfalls
4. Be specific enough for a Builder agent to implement without ambiguity

Format your response as a structured plan with numbered steps.
Be concise but complete. Think like a senior software architect."""


class PlannerAgent(BaseAgent):
    role = "planner"
    system_prompt = PLANNER_SYSTEM_PROMPT

    async def run(self, state: AgentState) -> dict:
        messages = [
            SystemMessage(content=self.system_prompt),
            HumanMessage(content=f"Task: {state['current_task']}\n\nProject path: {state['project_path']}"),
        ]
        response = await self.llm_with_tools.ainvoke(messages)
        plan = str(response.content)
        return {
            "messages": [response],
            "plan": plan,
            "active_agent": "builder",
        }


def create_planner_node(provider_type: str, model_id: str, api_key: str, base_url: str | None = None):
    agent = PlannerAgent(provider_type, model_id, api_key, base_url)
    async def node(state: AgentState) -> dict:
        return await agent.run(state)
    return node
