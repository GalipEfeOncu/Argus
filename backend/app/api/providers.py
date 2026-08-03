"""Provider profile endpoints; browser-facing requests never carry credentials."""

from __future__ import annotations

import hmac

from fastapi import APIRouter, Header, HTTPException, Response, status

from app.config import settings
from app.db.database import get_db
from app.schemas.provider import ManualModelRequest, NativeCredentialLeaseRequest, ProviderModelListResponse, ProviderProfileCreate, ProviderProfileResponse
from app.services.provider_profile_service import ProviderProfileError, ProviderProfileService

router = APIRouter()


def _http(error: ProviderProfileError) -> HTTPException:
    return HTTPException(404 if error.code == "provider_not_found" else 422, {"code": error.code, "message": error.message})


@router.get("/", response_model=list[ProviderProfileResponse])
async def list_profiles() -> list[ProviderProfileResponse]:
    db = await get_db()
    try:
        return await ProviderProfileService(db).list()
    finally:
        await db.close()


@router.post("/", response_model=ProviderProfileResponse, status_code=status.HTTP_201_CREATED)
async def create_profile(value: ProviderProfileCreate) -> ProviderProfileResponse:
    db = await get_db()
    try:
        return await ProviderProfileService(db).create(value)
    finally:
        await db.close()


@router.delete("/{profile_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_profile(profile_id: str) -> Response:
    db = await get_db()
    try:
        await ProviderProfileService(db).delete(profile_id)
    except ProviderProfileError as error:
        raise _http(error) from error
    finally:
        await db.close()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{profile_id}/models", response_model=ProviderModelListResponse)
async def discover_models(profile_id: str, manual: ManualModelRequest | None = None) -> ProviderModelListResponse:
    db = await get_db()
    try:
        return await ProviderProfileService(db).models(profile_id, manual)
    except ProviderProfileError as error:
        raise _http(error) from error
    finally:
        await db.close()


@router.put("/{profile_id}/credential", status_code=status.HTTP_204_NO_CONTENT, include_in_schema=False)
async def lease_credential(profile_id: str, value: NativeCredentialLeaseRequest, x_argus_bridge_token: str | None = Header(default=None)) -> Response:
    _require_native_bridge(x_argus_bridge_token)
    db = await get_db()
    try:
        await ProviderProfileService(db).lease_credential(profile_id, value.credential_reference, value.credential.get_secret_value())
    except ProviderProfileError as error:
        raise _http(error) from error
    finally:
        await db.close()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{profile_id}/credential-reference", include_in_schema=False)
async def native_credential_reference(profile_id: str, x_argus_bridge_token: str | None = Header(default=None)) -> dict[str, str | None]:
    _require_native_bridge(x_argus_bridge_token)
    db = await get_db()
    try:
        return {"credentialReference": (await ProviderProfileService(db).get(profile_id)).credential_reference}
    except ProviderProfileError as error:
        raise _http(error) from error
    finally:
        await db.close()


def _require_native_bridge(token: str | None) -> None:
    expected = settings.native_bridge_token
    if not expected or token is None or not hmac.compare_digest(expected.encode(), token.encode()):
        raise HTTPException(403, {"code": "native_bridge_required", "message": "Credential handoff requires the native bridge."})
