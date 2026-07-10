import asyncio
import subprocess
from pathlib import Path
from langchain_core.tools import tool


@tool
def shell_exec(command: str, cwd: str = "", timeout: int = 60) -> str:
    """
    Execute a shell command in the project directory.
    Returns stdout + stderr output.
    Use for: running tests, installing deps, running scripts.
    CAUTION: Avoid destructive commands (rm -rf, format, etc.)
    """
    # Basic safety checks
    dangerous = ["rm -rf /", "format", "mkfs", "dd if=", "> /dev/", ":(){ :|:"]
    for d in dangerous:
        if d in command:
            return f"Error: Refused to run potentially destructive command: {command}"

    try:
        result = subprocess.run(
            command,
            shell=True,
            cwd=cwd or None,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        output = result.stdout + result.stderr
        if not output:
            output = "(no output)"
        status = "✓" if result.returncode == 0 else f"✗ (exit {result.returncode})"
        return f"{status} $ {command}\n{output[:4000]}"
    except subprocess.TimeoutExpired:
        return f"Error: Command timed out after {timeout}s: {command}"
    except Exception as e:
        return f"Error running command: {e}"
