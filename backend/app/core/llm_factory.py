from typing import TYPE_CHECKING

from app.providers.adapters import ProviderKind, create_chat_model

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel


def create_llm(
    provider_type: str,
    model_id: str,
    api_key: str,
    base_url: str | None = None,
) -> "BaseChatModel":
    """
    Universal LLM factory.
    Supports Anthropic, Google, and any OpenAI-compatible endpoint
    (OpenAI, OpenRouter, Ollama, LM Studio, etc.)
    """
    supported_kind: ProviderKind = provider_type if provider_type in {
        "anthropic", "google", "openai", "openai_compat"
    } else "openai_compat"
    return create_chat_model(
        supported_kind,
        model_id=model_id,
        api_key=api_key,
        base_url=base_url,
    )
