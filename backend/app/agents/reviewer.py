from langchain_core.messages import HumanMessage, SystemMessage
from .state import AgentState
from .base_agent import BaseAgent


REVIEWER_SYSTEM_PROMPT = """You are the Reviewer agent in a multi-agent software development team.
You review code changes made by the Builder and provide detailed feedback.

Your responsibilities:
1. Read the modified files using read_file tool
2. Check for: bugs, security vulnerabilities, performance issues, code quality
3. Provide a clear decision:
   - APPROVED: Code is ready to test
   - REVISION_NEEDED: Specific issues to fix (list them clearly)
   - REJECTED: Fundamental problems, needs complete rethinking

Start your response with one of: [APPROVED], [REVISION_NEEDED], or [REJECTED]
Then explain your reasoning."""


class ReviewerAgent(BaseAgent):
    role = "reviewer"
    system_prompt = REVIEWER_SYSTEM_PROMPT

    async def run(self, state: AgentState) -> dict:
        messages = [
            SystemMessage(content=self.system_prompt),
            HumanMessage(
                content=(
                    f"Task: {state['current_task']}\n\n"
                    f"Project path: {state['project_path']}\n\n"
                    f"Please review the recent changes made by the Builder agent."
                )
            ),
        ]
        response = await self.llm_with_tools.ainvoke(messages)
        content = str(response.content)

        # Parse decision
        if "[APPROVED]" in content:
            status = "approved"
        elif "[REJECTED]" in content:
            status = "rejected"
        else:
            status = "revision_needed"

        return {
            "messages": [response],
            "review_status": status,
            "review_feedback": content,
            "active_agent": "tester" if status == "approved" else "builder",
        }


def create_reviewer_node(provider_type: str, model_id: str, api_key: str, base_url: str | None = None, tools=None):
    agent = ReviewerAgent(provider_type, model_id, api_key, base_url, tools=tools)
    async def node(state: AgentState) -> dict:
        return await agent.run(state)
    return node
