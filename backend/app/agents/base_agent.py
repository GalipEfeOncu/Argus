from abc import ABC, abstractmethod
from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool
from app.core.llm_factory import create_llm


class BaseAgent(ABC):
    """Base class for all Argus agents."""

    role: str
    system_prompt: str

    def __init__(
        self,
        provider_type: str,
        model_id: str,
        api_key: str,
        base_url: str | None = None,
        tools: list[BaseTool] | None = None,
        custom_system_prompt: str | None = None,
    ):
        self.llm: BaseChatModel = create_llm(provider_type, model_id, api_key, base_url)
        self.tools = tools or []
        if custom_system_prompt:
            self.system_prompt = custom_system_prompt

        # Bind tools if any
        if self.tools:
            self.llm_with_tools = self.llm.bind_tools(self.tools)  # type: ignore
        else:
            self.llm_with_tools = self.llm

    @abstractmethod
    async def run(self, state: dict) -> dict:
        """Execute the agent's task. Returns state updates."""
        ...
