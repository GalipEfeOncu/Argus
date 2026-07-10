import os
from pathlib import Path
from langchain_core.tools import tool


@tool
def read_file(path: str, project_path: str = "") -> str:
    """Read the contents of a file. Use absolute path or path relative to project_path."""
    full_path = Path(project_path) / path if project_path and not Path(path).is_absolute() else Path(path)
    try:
        content = full_path.read_text(encoding="utf-8")
        lines = content.splitlines()
        numbered = "\n".join(f"{i+1:4d}: {line}" for i, line in enumerate(lines))
        return f"File: {full_path}\nLines: {len(lines)}\n\n{numbered}"
    except FileNotFoundError:
        return f"Error: File not found: {full_path}"
    except Exception as e:
        return f"Error reading {full_path}: {e}"


@tool
def write_file(path: str, content: str, project_path: str = "") -> str:
    """Create or overwrite a file with the given content."""
    full_path = Path(project_path) / path if project_path and not Path(path).is_absolute() else Path(path)
    try:
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content, encoding="utf-8")
        lines = len(content.splitlines())
        return f"✓ Written {lines} lines to {full_path}"
    except Exception as e:
        return f"Error writing {full_path}: {e}"


@tool
def edit_file(path: str, old_content: str, new_content: str, project_path: str = "") -> str:
    """Replace a specific section of a file. Finds old_content and replaces with new_content."""
    full_path = Path(project_path) / path if project_path and not Path(path).is_absolute() else Path(path)
    try:
        original = full_path.read_text(encoding="utf-8")
        if old_content not in original:
            return f"Error: Could not find the specified content in {full_path}. Make sure the content matches exactly."
        updated = original.replace(old_content, new_content, 1)
        full_path.write_text(updated, encoding="utf-8")
        return f"✓ Edited {full_path} successfully"
    except FileNotFoundError:
        return f"Error: File not found: {full_path}"
    except Exception as e:
        return f"Error editing {full_path}: {e}"


@tool
def list_dir(path: str, project_path: str = "") -> str:
    """List the contents of a directory recursively (max 3 levels)."""
    full_path = Path(project_path) / path if project_path and not Path(path).is_absolute() else Path(path)
    try:
        result = []
        def walk(p: Path, prefix: str = "", depth: int = 0):
            if depth > 3:
                return
            try:
                items = sorted(p.iterdir(), key=lambda x: (x.is_file(), x.name))
                for item in items:
                    if item.name.startswith(".") or item.name in ("node_modules", "__pycache__", ".venv"):
                        continue
                    icon = "📁" if item.is_dir() else "📄"
                    result.append(f"{prefix}{icon} {item.name}")
                    if item.is_dir():
                        walk(item, prefix + "  ", depth + 1)
            except PermissionError:
                pass
        walk(full_path)
        return "\n".join(result) or "(empty directory)"
    except FileNotFoundError:
        return f"Error: Directory not found: {full_path}"
