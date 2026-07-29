from pydantic_settings import BaseSettings
from pathlib import Path


class Settings(BaseSettings):
    host: str = "127.0.0.1"
    port: int = 8000
    debug: bool = True
    db_path: str = str(Path.home() / ".argus" / "argus.db")
    state_db_path: str = str(Path.home() / ".argus" / "argus_state.db")
    native_bridge_token: str = ""

    class Config:
        env_prefix = "ARGUS_"
        env_file = ".env"


settings = Settings()
