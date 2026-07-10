import subprocess
from langchain_core.tools import tool


def _git(args: list[str], cwd: str) -> str:
    try:
        result = subprocess.run(
            ["git"] + args, cwd=cwd, capture_output=True, text=True, timeout=30
        )
        return result.stdout + result.stderr
    except Exception as e:
        return f"Git error: {e}"


@tool
def git_status(project_path: str) -> str:
    """Get the current git status of the project."""
    return _git(["status", "--short"], project_path)


@tool
def git_diff(project_path: str, staged: bool = False) -> str:
    """Get git diff of recent changes."""
    args = ["diff", "--stat"] + (["--cached"] if staged else [])
    return _git(args, project_path)[:3000]


@tool
def git_commit(project_path: str, message: str) -> str:
    """Stage all changes and create a git commit."""
    _git(["add", "-A"], project_path)
    return _git(["commit", "-m", message], project_path)
