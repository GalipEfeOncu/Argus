import subprocess
from pathlib import Path
from langchain_core.tools import tool


@tool
def search_files(pattern: str, path: str, file_types: str = "") -> str:
    """
    Search for a pattern in files using ripgrep (or grep fallback).
    pattern: regex or literal string to search
    path: directory to search in
    file_types: comma-separated extensions like 'py,ts,tsx'
    """
    try:
        cmd = ["rg", "--line-number", "--color=never", "--max-count=5"]
        if file_types:
            for ext in file_types.split(","):
                cmd += ["-g", f"*.{ext.strip()}"]
        cmd += [pattern, path]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        output = result.stdout
        if not output:
            # Fallback to grep
            grep_cmd = ["grep", "-rn", "--include=*.*", pattern, path]
            result2 = subprocess.run(grep_cmd, capture_output=True, text=True, timeout=15)
            output = result2.stdout
        return output[:3000] or f"No matches found for '{pattern}' in {path}"
    except FileNotFoundError:
        return f"ripgrep/grep not found. Pattern '{pattern}' could not be searched."
    except Exception as e:
        return f"Search error: {e}"
