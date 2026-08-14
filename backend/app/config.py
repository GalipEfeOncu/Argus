from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ARGUS_", env_file=".env")

    host: str = "127.0.0.1"
    port: int = 8000
    debug: bool = True
    db_path: str = str(Path.home() / ".argus" / "argus.db")
    state_db_path: str = str(Path.home() / ".argus" / "argus_state.db")
    native_bridge_token: str = ""
    access_token: str = ""
    allowed_origins: str = "tauri://localhost,http://tauri.localhost,http://localhost:1420,http://127.0.0.1:1420"

settings = Settings()
