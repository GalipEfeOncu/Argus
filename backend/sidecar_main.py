"""Frozen Argus sidecar entry point; configuration is injected by Tauri."""

from __future__ import annotations

import sys

import uvicorn

from app.config import settings
from app.main import app


def main() -> None:
    if sys.argv[1:] == ["--provider-packaging-smoke"]:
        from app.providers.packaging_smoke import run_provider_packaging_smoke

        print(run_provider_packaging_smoke())
        return
    config = uvicorn.Config(
        app=app,
        host=settings.host,
        port=settings.port,
        log_level="warning",
        access_log=False,
        server_header=False,
        workers=1,
    )
    server = uvicorn.Server(config)
    app.state.request_sidecar_shutdown = lambda: setattr(server, "should_exit", True)
    server.run()


if __name__ == "__main__":
    main()
