"""Provider-profile lookup indexes; credentials remain external references."""

from __future__ import annotations

import aiosqlite


async def apply(db: aiosqlite.Connection) -> None:
    await db.executescript("""
        CREATE INDEX IF NOT EXISTS idx_provider_profiles_display_name ON provider_profiles(display_name, created_at_ms);
        CREATE TRIGGER IF NOT EXISTS provider_profiles_native_credential_reference_insert
        BEFORE INSERT ON provider_profiles
        WHEN NEW.credential_reference IS NOT NULL AND (length(NEW.credential_reference) != 51 OR NEW.credential_reference NOT GLOB 'argus-provider-????????-????-????-????-????????????')
        BEGIN SELECT RAISE(ABORT, 'credential reference must be native opaque format'); END;
        CREATE TRIGGER IF NOT EXISTS provider_profiles_native_credential_reference_update
        BEFORE UPDATE OF credential_reference ON provider_profiles
        WHEN NEW.credential_reference IS NOT NULL AND (length(NEW.credential_reference) != 51 OR NEW.credential_reference NOT GLOB 'argus-provider-????????-????-????-????-????????????')
        BEGIN SELECT RAISE(ABORT, 'credential reference must be native opaque format'); END;
        CREATE TRIGGER IF NOT EXISTS provider_profiles_no_credential_in_metadata_insert
        BEFORE INSERT ON provider_profiles
        WHEN lower(NEW.metadata_json) LIKE '%api_key%' OR lower(NEW.metadata_json) LIKE '%credential%'
        BEGIN SELECT RAISE(ABORT, 'provider metadata must not contain credentials'); END;
        CREATE TRIGGER IF NOT EXISTS provider_profiles_no_credential_in_metadata_update
        BEFORE UPDATE OF metadata_json ON provider_profiles
        WHEN lower(NEW.metadata_json) LIKE '%api_key%' OR lower(NEW.metadata_json) LIKE '%credential%'
        BEGIN SELECT RAISE(ABORT, 'provider metadata must not contain credentials'); END;
    """)
