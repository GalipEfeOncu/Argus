from __future__ import annotations

import importlib.util
from pathlib import Path
import tomllib


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def _load_attribution_module():
    path = REPOSITORY_ROOT / "scripts" / "sidecar-attribution.py"
    spec = importlib.util.spec_from_file_location("sidecar_attribution", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_sidecar_build_collects_supported_provider_adapters_and_keeps_them_out_of_exclusions() -> None:
    build_script = (REPOSITORY_ROOT / "scripts" / "build-sidecar.sh").read_text(encoding="utf-8")
    project = tomllib.loads((REPOSITORY_ROOT / "backend" / "pyproject.toml").read_text(encoding="utf-8"))
    attribution = _load_attribution_module()
    expected = ["langchain_openai", "langchain_anthropic", "langchain_google_genai"]
    packaging = project["project"]["optional-dependencies"]["packaging"]

    assert attribution.INCLUDED_PROVIDER_ADAPTERS == expected
    for module in expected:
        assert f"--hidden-import {module}" in build_script
        assert f"--exclude-module {module}" not in build_script
        assert module not in attribution.EXCLUDED_MODULES
    for distribution in ("langchain-openai", "langchain-anthropic", "langchain-google-genai"):
        assert any(requirement.startswith(distribution) for requirement in packaging)
    assert "--providers-only" in build_script


def test_provider_adapter_sources_have_separate_size_attribution() -> None:
    attribution = _load_attribution_module()

    assert attribution.category(Path("/runtime/site-packages/langchain_openai/chat_models/base.py")) == "provider-adapters"
    assert attribution.category(Path("/runtime/site-packages/fastapi/applications.py")) == "base-dependencies"


def test_analysis_attribution_reads_module_sources_without_exposing_their_paths(tmp_path: Path) -> None:
    attribution = _load_attribution_module()
    toc = tmp_path / "Analysis-00.toc"
    toc.write_text(repr(([], [], ["hidden_import"], [], {}, [], [], False, {}, 0, [], [], "", [], [
        ("langchain_openai.chat_models", "/runtime/site-packages/langchain_openai/chat_models/base.py", "PYMODULE"),
    ])), encoding="utf-8")

    assert attribution.analysis_sources(toc) == [Path("/runtime/site-packages/langchain_openai/chat_models/base.py")]
