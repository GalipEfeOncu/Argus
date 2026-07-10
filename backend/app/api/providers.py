from fastapi import APIRouter
from app.schemas.provider import ProviderTestRequest, ProviderTestResponse, ModelsListRequest
from app.core.llm_factory import test_provider

router = APIRouter()


@router.post("/test", response_model=ProviderTestResponse)
async def test_provider_endpoint(req: ProviderTestRequest):
    valid, error, latency_ms = await test_provider(req)
    return ProviderTestResponse(valid=valid, error=error, latency_ms=latency_ms)


@router.post("/models")
async def list_models(req: ModelsListRequest):
    """
    Fetch available models from a provider.
    For OpenAI-compat, calls /models endpoint.
    For Anthropic/Google, returns known model list.
    """
    if req.type == "anthropic":
        return {"models": [
            {"id": "claude-opus-4-20250514", "display_name": "Claude Opus 4"},
            {"id": "claude-sonnet-4-20250514", "display_name": "Claude Sonnet 4"},
            {"id": "claude-haiku-4-20250514", "display_name": "Claude Haiku 4"},
        ]}
    elif req.type == "google":
        return {"models": [
            {"id": "gemini-2.5-pro", "display_name": "Gemini 2.5 Pro"},
            {"id": "gemini-2.5-flash", "display_name": "Gemini 2.5 Flash"},
            {"id": "gemini-2.0-flash", "display_name": "Gemini 2.0 Flash (Free)"},
        ]}
    else:
        # OpenAI-compat: try to fetch from /models endpoint
        try:
            import httpx
            headers = {"Authorization": f"Bearer {req.api_key}"}
            base = req.base_url or "https://api.openai.com/v1"
            async with httpx.AsyncClient() as client:
                resp = await client.get(f"{base}/models", headers=headers, timeout=10)
                data = resp.json()
                models = [
                    {"id": m["id"], "display_name": m["id"]}
                    for m in sorted(data.get("data", []), key=lambda x: x["id"])
                ]
                return {"models": models}
        except Exception as e:
            return {"models": [], "error": str(e)}
