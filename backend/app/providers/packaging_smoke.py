"""Offline verification for provider modules embedded in a frozen sidecar."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

from app.providers.adapters import LangChainProvider, ProviderKind, create_chat_model
from app.providers.protocol import Finished, ProviderRequest, TextDelta, Usage

_PROVIDER_KINDS: tuple[ProviderKind, ...] = ("openai", "openai_compat", "anthropic", "google")


class _SyntheticModel:
    async def astream(self, _: list[dict[str, object]]):
        yield SimpleNamespace(
            content="offline smoke",
            tool_calls=[],
            additional_kwargs={},
            usage_metadata={"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
            response_metadata={"finish_reason": "stop"},
        )


async def _normalize_synthetic_stream() -> None:
    request = ProviderRequest(
        request_id="provider-packaging-smoke",
        model_id="offline-smoke-model",
        messages=({"role": "user", "content": "offline smoke"},),
    )
    events = [event async for event in LangChainProvider(_SyntheticModel()).stream(request)]
    expected = [
        TextDelta("offline smoke"),
        Usage(input_tokens=1, output_tokens=1, total_tokens=2),
        Finished(),
    ]
    if events != expected:
        raise RuntimeError("The packaged provider adapter failed its synthetic stream check.")


def run_provider_packaging_smoke() -> str:
    """Construct every supported SDK adapter without credentials, network, or persistence."""

    for provider_kind in _PROVIDER_KINDS:
        model = create_chat_model(
            provider_kind,
            model_id="offline-smoke-model",
            api_key="offline-smoke-value",
            base_url="https://example.invalid/v1" if provider_kind == "openai_compat" else None,
        )
        if not callable(getattr(model, "astream", None)):
            raise RuntimeError("A packaged provider adapter does not expose streaming.")
    asyncio.run(_normalize_synthetic_stream())
    return json.dumps({"providerPackagingSmoke": "ok", "providers": list(_PROVIDER_KINDS)}, sort_keys=True)
