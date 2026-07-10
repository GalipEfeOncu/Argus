from fastapi import APIRouter

router = APIRouter()

# Placeholder — model listing is handled in providers.py
@router.get("/")
async def list_available_models():
    return {"message": "Use /providers/models to list models for a specific provider"}
