"""LangChain adapters for the session-bound workspace tool service.

The legacy tool modules accept a user-controlled project path and are not used
by the canonical workspace flow. These adapters capture the resolved session
workspace once, so model arguments cannot choose another host directory.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
import subprocess
import uuid

from langchain_core.tools import BaseTool, tool

from app.config import settings
from app.db.database import get_db
from app.services.workspace_service import (
    ProjectWorkspaceService,
    ScopedToolService,
    WorkspaceError,
    WorkspaceRecord,
    resolve_workspace_path,
)


def _result_error(error: Exception) -> str:
    return f"Error: {error}"


def create_scoped_tools(workspace: WorkspaceRecord) -> list[BaseTool]:
    service = ScopedToolService(workspace)
    mutation_lock = asyncio.Lock()
    holder_id = f"legacy-worker:{uuid.uuid4()}"

    async def mutating(operation):
        """Serialize mutations under a durable lease and persist their revision."""
        async with mutation_lock:
            database = await get_db()
            lifecycle = ProjectWorkspaceService(
                database, managed_root=Path(settings.db_path).expanduser().resolve().parent / "workspaces"
            )
            lease_id: str | None = None
            try:
                lease_id = await lifecycle.acquire_writer_lease(
                    project_id=workspace.project_id, session_id=workspace.session_id, holder_id=holder_id,
                )
                result = await asyncio.to_thread(operation)
                await lifecycle.record_mutation(workspace.session_id)
                return result
            finally:
                if lease_id is not None:
                    await lifecycle.release_writer_lease(lease_id, holder_id=holder_id, reason="tool_completed")
                await database.close()

    @tool
    def read_file(path: str) -> str:
        """Read a UTF-8 file at a path relative to the active session workspace."""
        try:
            return service.read_text(path)
        except (OSError, WorkspaceError) as error:
            return _result_error(error)

    @tool
    async def write_file(path: str, content: str) -> str:
        """Write a UTF-8 file at a path relative to the active session workspace."""
        try:
            await mutating(lambda: service.write_text(path, content))
            return f"Written {path}"
        except (OSError, WorkspaceError) as error:
            return _result_error(error)

    @tool
    def list_dir(path: str = ".") -> str:
        """List one directory inside the active session workspace."""
        try:
            directory = resolve_workspace_path(workspace.root_path, path, must_exist=True)
            if not directory.is_dir():
                return "Error: path is not a directory"
            return "\n".join(sorted(item.name for item in directory.iterdir() if not item.is_symlink()))
        except (OSError, WorkspaceError) as error:
            return _result_error(error)

    @tool
    def search_files(pattern: str, path: str = ".", file_types: str = "") -> str:
        """Search relative workspace files using ripgrep; patterns never select another root."""
        try:
            directory = resolve_workspace_path(workspace.root_path, path, must_exist=True)
            argv = ["rg", "--line-number", "--color=never", "--max-count=5"]
            for extension in filter(None, (item.strip() for item in file_types.split(","))):
                argv.extend(("-g", f"*.{extension}"))
            relative_directory = directory.relative_to(workspace.root_path).as_posix()
            argv.extend((pattern, "." if relative_directory == "." else relative_directory))
            result = service.run(argv, timeout_seconds=15)
            return (result.stdout or result.stderr or "No matches found")[:3000]
        except (OSError, WorkspaceError) as error:
            return _result_error(error)

    @tool
    async def shell_exec(argv: list[str], timeout: int = 60) -> str:
        """Run a non-destructive argv command in the active session workspace; shell expressions are unsupported."""
        try:
            result = await mutating(lambda: service.run(argv, timeout_seconds=min(max(timeout, 1), 300)))
            output = result.stdout + result.stderr
            return f"{'OK' if result.returncode == 0 else f'Exit {result.returncode}'}\n{output[:4000]}"
        except (OSError, WorkspaceError, subprocess.TimeoutExpired) as error:
            return _result_error(error)

    @tool
    async def git_status() -> str:
        """Get git status for the active session workspace."""
        return await shell_exec.ainvoke({"argv": ["git", "status", "--short", "--no-untracked-files"]})

    @tool
    async def git_diff() -> str:
        """Get a bounded git diff summary for the active session workspace."""
        return await shell_exec.ainvoke({"argv": ["git", "diff", "--stat", "--no-ext-diff"]})

    return [read_file, write_file, list_dir, search_files, shell_exec, git_status, git_diff]
