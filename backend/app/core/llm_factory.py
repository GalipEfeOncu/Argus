from typing import TYPE_CHECKING

from app.providers.adapters import ProviderKind, create_chat_model
from app.schemas.provider import ProviderTestRequest

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


async def test_provider(req: ProviderTestRequest) -> tuple[bool, str | None, int | None]:
    """Test a provider connection. Returns (valid, error_msg, latency_ms)."""
    import time
    try:
        llm = create_llm(
            provider_type=req.type,
            model_id=req.model_id or _default_test_model(req.type),
            api_key=req.api_key,
            base_url=req.base_url,
        )
        start = time.monotonic()
        await llm.ainvoke([{"role": "user", "content": "Say 'ok' in one word."}])
        latency_ms = int((time.monotonic() - start) * 1000)
        return True, None, latency_ms
    except Exception as e:
        return False, str(e), None


def _default_test_model(provider_type: str) -> str:
    match provider_type:
        case "anthropic": return "claude-haiku-4-20250514"
        case "google": return "gemini-2.0-flash"
        case _: return "gpt-4o-mini"
