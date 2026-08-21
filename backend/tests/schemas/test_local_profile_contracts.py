import pytest
from pydantic import ValidationError

from app.schemas.local_profile import LocalProfilePatch


def test_local_profile_patch_normalizes_safe_unicode_content() -> None:
    value = LocalProfilePatch.model_validate({"displayName": "  İpek  ", "bio": "   "})

    assert value.display_name == "İpek"
    assert value.bio is None
    assert value.model_fields_set == {"display_name", "bio"}


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"displayName": None},
        {"displayName": ""},
        {"displayName": "a" * 81},
        {"displayName": "Ada\nLovelace"},
        {"bio": "unsafe\x00text"},
        {"bio": "b" * 281},
        {"email": "person@example.invalid"},
        {"password": "not-accepted"},
        {"token": "not-accepted"},
        {"plan": "pro"},
    ],
)
def test_local_profile_patch_rejects_empty_unsafe_or_non_profile_fields(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        LocalProfilePatch.model_validate(payload)


def test_local_profile_patch_allows_explicit_bio_clear() -> None:
    value = LocalProfilePatch.model_validate({"bio": None})

    assert value.bio is None
    assert value.model_fields_set == {"bio"}
