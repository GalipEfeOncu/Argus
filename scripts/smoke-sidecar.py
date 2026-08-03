"""Black-box smoke probe for a frozen authenticated Argus sidecar."""

from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def status(url: str, *, token: str | None = None, origin: str | None = None, method: str = "GET") -> int:
    headers = {}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    if origin is not None:
        headers["Origin"] = origin
    try:
        with urlopen(Request(url, headers=headers, method=method), timeout=2) as response:
            return response.status
    except HTTPError as error:
        return error.code


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: smoke-sidecar.py <frozen-sidecar>")
    binary = Path(sys.argv[1]).resolve()
    if not binary.is_file():
        raise SystemExit(f"Sidecar does not exist: {binary}")
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    token = "argus-sidecar-smoke-token"
    with tempfile.TemporaryDirectory(prefix="argus-sidecar-smoke-") as directory:
        environment = {
            **os.environ,
            "ARGUS_HOST": "127.0.0.1",
            "ARGUS_PORT": str(port),
            "ARGUS_ACCESS_TOKEN": token,
            "ARGUS_NATIVE_BRIDGE_TOKEN": "argus-sidecar-smoke-bridge",
            "ARGUS_DB_PATH": str(Path(directory) / "argus.db"),
        }
        process = subprocess.Popen([str(binary)], env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            health_url = f"http://127.0.0.1:{port}/health"
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    stdout, stderr = process.communicate()
                    raise RuntimeError(f"Sidecar exited before readiness: {stdout} {stderr}")
                try:
                    if status(health_url, token=token) == 200:
                        break
                except OSError:
                    time.sleep(0.1)
            else:
                raise RuntimeError("Sidecar readiness timed out")
            results = {
                "unauthorized": status(health_url),
                "authorized": status(health_url, token=token),
                "unexpectedOrigin": status(health_url, token=token, origin="https://unexpected.invalid"),
                "shutdown": status(f"http://127.0.0.1:{port}/runtime/shutdown", token=token, method="POST"),
            }
            if results != {"unauthorized": 401, "authorized": 200, "unexpectedOrigin": 403, "shutdown": 202}:
                raise RuntimeError(f"Unexpected sidecar responses: {results}")
            process.wait(timeout=5)
            if process.returncode not in (0, -signal.SIGTERM):
                raise RuntimeError(f"Sidecar exited with {process.returncode}")
            print(json.dumps(results, sort_keys=True))
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=5)


if __name__ == "__main__":
    main()
