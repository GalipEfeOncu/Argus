"""Supported provider presets and their non-secret defaults."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


ProviderKind = Literal["openai", "openai_compat", "anthropic", "google"]
ProviderPreset = Literal[
    "openai",
    "anthropic",
    "google",
    "openrouter",
    "deepseek",
    "kimi",
    "xai",
    "mistral",
    "groq",
    "ollama",
    "custom",
]


@dataclass(frozen=True)
class ProviderDefinition:
    preset: ProviderPreset
    display_name: str
    provider_kind: ProviderKind
    default_endpoint: str | None
    credential_required: bool
    fallback_model_ids: tuple[str, ...] = ()


PROVIDER_DEFINITIONS: tuple[ProviderDefinition, ...] = (
    ProviderDefinition("openai", "OpenAI", "openai", None, True, ("gpt-4o-mini",)),
    ProviderDefinition("anthropic", "Anthropic", "anthropic", None, True, ("claude-sonnet-4-20250514",)),
    ProviderDefinition("google", "Google Gemini", "google", None, True, ("gemini-2.5-flash",)),
    ProviderDefinition("openrouter", "OpenRouter", "openai_compat", "https://openrouter.ai/api/v1", True, ("openrouter/free",)),
    ProviderDefinition("deepseek", "DeepSeek", "openai_compat", "https://api.deepseek.com", True, ("deepseek-v4-flash", "deepseek-v4-pro")),
    ProviderDefinition("kimi", "Moonshot / Kimi", "openai_compat", "https://api.moonshot.ai/v1", True, ("kimi-k2.6", "kimi-k2.5")),
    ProviderDefinition("xai", "xAI", "openai_compat", "https://api.x.ai/v1", True, ("grok-4",)),
    ProviderDefinition("mistral", "Mistral AI", "openai_compat", "https://api.mistral.ai/v1", True, ("mistral-large-latest",)),
    ProviderDefinition("groq", "Groq", "openai_compat", "https://api.groq.com/openai/v1", True, ("openai/gpt-oss-20b",)),
    ProviderDefinition("ollama", "Ollama (Local)", "openai_compat", "http://localhost:11434/v1", False, ()),
    ProviderDefinition("custom", "Custom OpenAI-compatible", "openai_compat", None, True, ()),
)

_BY_PRESET = {item.preset: item for item in PROVIDER_DEFINITIONS}


def provider_definition(preset: ProviderPreset) -> ProviderDefinition:
    return _BY_PRESET[preset]


def resolve_provider_preset(
    preset: ProviderPreset | None,
    provider_kind: ProviderKind,
    endpoint: str | None,
) -> ProviderDefinition:
    """Resolve new and legacy profiles without persisting secrets."""

    if isinstance(preset, str) and preset in _BY_PRESET:
        return provider_definition(preset)
    normalized = (endpoint or "").lower()
    for candidate in PROVIDER_DEFINITIONS:
        if candidate.default_endpoint and candidate.default_endpoint.lower() == normalized:
            return candidate
    if provider_kind == "openai":
        return provider_definition("openai")
    if provider_kind == "anthropic":
        return provider_definition("anthropic")
    if provider_kind == "google":
        return provider_definition("google")
    return provider_definition("custom")
