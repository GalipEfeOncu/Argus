from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


SCRIPT_PATH = Path(__file__).resolve().parents[3] / "scripts" / "supply_chain.py"
SPEC = importlib.util.spec_from_file_location("supply_chain", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
supply_chain = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(supply_chain)


def test_directory_comparison_and_checksums_are_deterministic(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    (first / "app.js").write_text("same")
    (second / "app.js").write_text("same")

    supply_chain.compare_builds(first, second)
    output = tmp_path / "SHA256SUMS"
    supply_chain.write_checksums(first, output)
    assert output.read_text().endswith("  app.js\n")

    (second / "app.js").write_text("different")
    with pytest.raises(RuntimeError, match="app.js"):
        supply_chain.compare_builds(first, second)


def test_release_artifacts_reject_symlinks(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "real").write_text("data")
    (artifacts / "link").symlink_to(artifacts / "real")
    with pytest.raises(ValueError, match="symlink"):
        supply_chain.write_checksums(artifacts, tmp_path / "SHA256SUMS")


def test_release_staging_flattens_unique_assets_and_rejects_collisions(tmp_path: Path) -> None:
    source = tmp_path / "downloaded"
    (source / "windows").mkdir(parents=True)
    (source / "linux").mkdir()
    (source / "windows" / "argus.exe").write_text("windows")
    (source / "linux" / "argus.deb").write_text("linux")
    destination = tmp_path / "staged"
    supply_chain.stage_artifacts(source, destination)
    assert sorted(path.name for path in destination.iterdir()) == ["argus.deb", "argus.exe"]

    collision_source = tmp_path / "collision"
    (collision_source / "a").mkdir(parents=True)
    (collision_source / "b").mkdir()
    (collision_source / "a" / "same.bin").write_text("one")
    (collision_source / "b" / "same.bin").write_text("two")
    with pytest.raises(ValueError, match="collision"):
        supply_chain.stage_artifacts(collision_source, tmp_path / "collision-staged")


def test_release_workflow_stages_artifacts_before_separate_publication_approval() -> None:
    workflow = (SCRIPT_PATH.parents[1] / ".github" / "workflows" / "release.yml").read_text()

    stage = workflow.index("  stage:\n")
    publish = workflow.index("  publish:\n")
    assert stage < publish
    assert "name: argus-release-staged-${{ inputs.tag }}" in workflow[stage:publish]
    assert "environment: release-publication" in workflow[publish:]
    assert "(cd release-staging && sha256sum --check SHA256SUMS)" in workflow[publish:]


def test_release_workflow_bounds_unsigned_community_alpha() -> None:
    workflow = (SCRIPT_PATH.parents[1] / ".github" / "workflows" / "release.yml").read_text()

    assert "default: unsigned-community-alpha" in workflow
    assert '[[ "$RELEASE_TAG" == *-alpha.* ]]' in workflow
    assert 'test "$PRERELEASE" = true' in workflow
    assert "if: inputs.signing_mode == 'signed' && runner.os == 'Windows'" in workflow
    assert "if: inputs.signing_mode == 'signed' && runner.os == 'macOS'" in workflow
    assert "Path('release-staging/UNSIGNED-RELEASE.txt').write_text(" in workflow
    assert "'signingMode': os.environ['SIGNING_MODE']" in workflow
    assert "UNSIGNED COMMUNITY ALPHA" in workflow
    unsigned_build = workflow.index("      - name: Build unsigned community Alpha bundle\n")
    upload = workflow.index("      - uses: actions/upload-artifact@", unsigned_build)
    assert "secrets." not in workflow[unsigned_build:upload]


def test_workflows_pin_node24_artifact_and_secret_scan_actions() -> None:
    workflows = "\n".join(
        path.read_text()
        for path in sorted((SCRIPT_PATH.parents[1] / ".github" / "workflows").glob("*.yml"))
    )

    assert "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02" not in workflows
    assert "actions/download-artifact@634f93cb2916e3fdff6788551b99b062d0335ce0" not in workflows
    assert "gitleaks/gitleaks-action@dcedce43c6f43de0b836d1fe38946645c9c638dc" not in workflows
    assert "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a" in workflows
    assert "actions/download-artifact@3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c" in workflows
    assert "gitleaks/gitleaks-action@e0c47f4f8be36e29cdc102c57e68cb5cbf0e8d1e" in workflows


def test_sbom_is_reproducible_and_uses_locked_components(tmp_path: Path) -> None:
    (tmp_path / "backend").mkdir()
    (tmp_path / "src-tauri").mkdir()
    (tmp_path / "package.json").write_text('{"version":"1.2.3"}')
    (tmp_path / "package-lock.json").write_text(json.dumps({"packages": {"": {"version": "1.2.3"}, "node_modules/demo": {"version": "2.0.0"}}}))
    (tmp_path / "backend" / "uv.lock").write_text('version = 1\n[[package]]\nname = "py-demo"\nversion = "3.0.0"\nsource = { registry = "https://example.invalid" }\n')
    (tmp_path / "src-tauri" / "Cargo.lock").write_text('version = 4\n[[package]]\nname = "rs-demo"\nversion = "4.0.0"\nsource = "registry+https://example.invalid"\nchecksum = "abc"\n')
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"

    supply_chain.write_sbom(tmp_path, first)
    supply_chain.write_sbom(tmp_path, second)

    assert first.read_bytes() == second.read_bytes()
    document = json.loads(first.read_text())
    assert document["bomFormat"] == "CycloneDX"
    assert [item["purl"] for item in document["components"]] == [
        "pkg:cargo/rs-demo@4.0.0",
        "pkg:npm/demo@2.0.0",
        "pkg:pypi/py-demo@3.0.0",
    ]


@pytest.mark.parametrize("license_name", ["GPL-3.0", "NOASSERTION", "", "UNKNOWN", {"type": "MIT"}])
def test_license_audit_fails_closed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, license_name: object) -> None:
    (tmp_path / "supply-chain-license-policy.json").write_text(
        '{"forbidden":["GPL","AGPL","SSPL"],"metadataOverrides":[]}'
    )
    monkeypatch.setattr(
        supply_chain,
        "license_inventory",
        lambda _root: [{"ecosystem": "test", "name": "unsafe", "version": "1", "license": license_name}],
    )

    with pytest.raises(RuntimeError):
        supply_chain.write_license_audit(tmp_path, tmp_path / "licenses.json")
