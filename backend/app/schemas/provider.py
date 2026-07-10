from pydantic import BaseModel
from typing import Optional


class ProviderTestRequest(BaseModel):
    type: str  # "anthropic" | "openai_compat" | "google"
    api_key: str
    base_url: Optional[str] = None
    model_id: Optional[str] = None  # Optional model to test with


class ProviderTestResponse(BaseModel):
    valid: bool
    error: Optional[str] = None
    latency_ms: Optional[int] = None


class ModelsListRequest(BaseModel):
    type: str
    api_key: str
    base_url: Optional[str] = None


class ModelInfo(BaseModel):
    id: str
    display_name: str
    context_window: Optional[int] = None
