#!/usr/bin/env python3
"""Generate deterministic release evidence from Argus lockfiles and artifacts."""

from __future__ import annotations

import argparse
import base64
import fnmatch
from hashlib import sha256
import importlib.metadata
import json
from pathlib import Path
import re
import shutil
import subprocess
import tomllib
from urllib.parse import quote
import uuid


def _sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _integrity_hash(value: str | None) -> list[dict[str, str]]:
    if not value or "-" not in value:
        return []
    algorithm, encoded = value.split("-", 1)
    if algorithm.lower() not in {"sha256", "sha384", "sha512"}:
        return []
    try:
        content = base64.b64decode(encoded, validate=True).hex()
    except ValueError:
        return []
    return [{"alg": algorithm.upper().replace("SHA", "SHA-"), "content": content}]


def _component(ecosystem: str, name: str, version: str, *, hashes: list[dict[str, str]] | None = None) -> dict[str, object]:
    component: dict[str, object] = {
        "type": "library",
        "name": name,
        "version": version,
        "purl": f"pkg:{ecosystem}/{quote(name, safe='/')}@{quote(version, safe='')}",
    }
    if hashes:
        component["hashes"] = hashes
    return component


def lockfile_components(root: Path) -> list[dict[str, object]]:
    package_lock = json.loads((root / "package-lock.json").read_text())
    components: list[dict[str, object]] = []
    for path, package in package_lock.get("packages", {}).items():
        if not path or not package.get("version") or "node_modules/" not in path:
            continue
        name = path.rsplit("node_modules/", 1)[1]
        components.append(
            _component("npm", name, package["version"], hashes=_integrity_hash(package.get("integrity")))
        )

    uv_lock = tomllib.loads((root / "backend" / "uv.lock").read_text())
    for package in uv_lock.get("package", []):
        source = package.get("source", {})
        if "editable" in source or not package.get("version"):
            continue
        hashes: list[dict[str, str]] = []
        if package.get("sdist", {}).get("hash", "").startswith("sha256:"):
            hashes.append({"alg": "SHA-256", "content": package["sdist"]["hash"].split(":", 1)[1]})
        components.append(_component("pypi", package["name"], package["version"], hashes=hashes))

    cargo_lock = tomllib.loads((root / "src-tauri" / "Cargo.lock").read_text())
    for package in cargo_lock.get("package", []):
        if not package.get("source"):
            continue
        hashes = []
        if package.get("checksum"):
            hashes.append({"alg": "SHA-256", "content": package["checksum"]})
        components.append(_component("cargo", package["name"], package["version"], hashes=hashes))

    unique = {(item["purl"]): item for item in components}
    return [unique[key] for key in sorted(unique)]


def write_sbom(root: Path, output: Path) -> None:
    lockfiles = [root / "package-lock.json", root / "backend" / "uv.lock", root / "src-tauri" / "Cargo.lock"]
    fingerprint = sha256("".join(_sha256(path) for path in lockfiles).encode()).hexdigest()
    version = json.loads((root / "package.json").read_text())["version"]
    document = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "serialNumber": f"urn:uuid:{uuid.uuid5(uuid.NAMESPACE_URL, fingerprint)}",
        "version": 1,
        "metadata": {"component": {"type": "application", "name": "Argus", "version": version}},
        "components": lockfile_components(root),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")


def _python_licenses() -> dict[tuple[str, str], str]:
    result: dict[tuple[str, str], str] = {}
    for distribution in importlib.metadata.distributions():
        name = distribution.metadata.get("Name")
        if not name:
            continue
        expression = distribution.metadata.get("License-Expression") or distribution.metadata.get("License")
        if not expression or expression.strip().upper() == "UNKNOWN":
            classifiers = distribution.metadata.get_all("Classifier", [])
            expression = "; ".join(item.removeprefix("License :: ") for item in classifiers if item.startswith("License :: "))
        result[(name.lower().replace("_", "-"), distribution.version)] = expression.strip() if expression else "NOASSERTION"
    return result


def _license_override(
    overrides: list[dict[str, str]], ecosystem: str, name: str, version: str
) -> tuple[str, str] | None:
    for override in overrides:
        if (
            override["ecosystem"] == ecosystem
            and override["version"] == version
            and fnmatch.fnmatchcase(name, override["namePattern"])
        ):
            return override["license"], override["source"]
    return None


def _normalize_license(value: object) -> str:
    if not isinstance(value, str) or value.strip().upper() in {"", "UNKNOWN", "NONE", "N/A"}:
        return "NOASSERTION"
    return value.strip()


def _license_policy(root: Path) -> dict[str, object]:
    return json.loads((root / "supply-chain-license-policy.json").read_text())


def license_inventory(root: Path) -> list[dict[str, str]]:
    inventory: list[dict[str, str]] = []
    policy = _license_policy(root)
    overrides = policy["metadataOverrides"]
    package_lock = json.loads((root / "package-lock.json").read_text())
    for path, package in package_lock.get("packages", {}).items():
        if not path or "node_modules/" not in path or not package.get("version"):
            continue
        name = path.rsplit("node_modules/", 1)[1]
        metadata_path = root / path / "package.json"
        metadata = json.loads(metadata_path.read_text()) if metadata_path.is_file() else {}
        license_value = _normalize_license(metadata.get("license"))
        source = "installed-package-metadata"
        if license_value == "NOASSERTION" and (override := _license_override(overrides, "npm", name, package["version"])):
            license_value, source = override
        inventory.append({"ecosystem": "npm", "name": name, "version": package["version"], "license": license_value, "licenseSource": source})

    python_licenses = _python_licenses()
    uv_lock = tomllib.loads((root / "backend" / "uv.lock").read_text())
    for package in uv_lock.get("package", []):
        if "editable" in package.get("source", {}) or not package.get("version"):
            continue
        key = (package["name"].lower().replace("_", "-"), package["version"])
        license_value = _normalize_license(python_licenses.get(key))
        source = "installed-distribution-metadata"
        if license_value == "NOASSERTION" and (override := _license_override(overrides, "pypi", package["name"], package["version"])):
            license_value, source = override
        inventory.append({"ecosystem": "pypi", "name": package["name"], "version": package["version"], "license": license_value, "licenseSource": source})

    metadata = subprocess.run(
        ["cargo", "metadata", "--locked", "--format-version", "1", "--manifest-path", str(root / "src-tauri" / "Cargo.toml")],
        check=True,
        capture_output=True,
        text=True,
    )
    for package in json.loads(metadata.stdout)["packages"]:
        if package["name"] == "argus":
            continue
        license_value = _normalize_license(package.get("license"))
        source = "cargo-metadata"
        if license_value == "NOASSERTION" and (override := _license_override(overrides, "cargo", package["name"], package["version"])):
            license_value, source = override
        inventory.append({"ecosystem": "cargo", "name": package["name"], "version": package["version"], "license": license_value, "licenseSource": source})
    return sorted(inventory, key=lambda item: (item["ecosystem"], item["name"].lower(), item["version"]))


def write_license_audit(root: Path, output: Path) -> None:
    inventory = license_inventory(root)
    inventory = [{**item, "license": _normalize_license(item.get("license"))} for item in inventory]
    policy = _license_policy(root)
    forbidden_names = "|".join(re.escape(str(name)) for name in policy["forbidden"])
    forbidden_pattern = re.compile(
        rf"(^|[^A-Z])(?:{forbidden_names})(?:-|[^A-Z]|$)", re.IGNORECASE
    )
    forbidden = [item for item in inventory if forbidden_pattern.search(item["license"])]
    unresolved = [item for item in inventory if item["license"] == "NOASSERTION"]
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(
            {"dependencies": inventory, "forbidden": forbidden, "unresolved": unresolved},
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    if forbidden:
        names = ", ".join(f"{item['ecosystem']}:{item['name']}" for item in forbidden)
        raise RuntimeError(f"Forbidden dependency licenses detected: {names}")
    if unresolved:
        names = ", ".join(f"{item['ecosystem']}:{item['name']}" for item in unresolved[:20])
        raise RuntimeError(f"Dependency licenses require review: {names}")


def directory_manifest(directory: Path) -> dict[str, str]:
    manifest: dict[str, str] = {}
    for path in sorted(directory.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"Artifact tree contains a symlink: {path}")
        if path.is_file():
            manifest[path.relative_to(directory).as_posix()] = _sha256(path)
    return manifest


def compare_builds(first: Path, second: Path) -> None:
    first_manifest = directory_manifest(first)
    second_manifest = directory_manifest(second)
    if first_manifest != second_manifest:
        changed = sorted(set(first_manifest) ^ set(second_manifest) | {key for key in first_manifest.keys() & second_manifest.keys() if first_manifest[key] != second_manifest[key]})
        raise RuntimeError(f"Clean build outputs differ: {', '.join(changed[:20])}")


def write_checksums(directory: Path, output: Path) -> None:
    directory = directory.resolve(strict=True)
    output = output.resolve(strict=False)
    lines = []
    for path in sorted(directory.rglob("*")):
        if path == output:
            continue
        if path.is_symlink():
            raise ValueError(f"Release artifacts must not contain symlinks: {path}")
        if path.is_file():
            lines.append(f"{_sha256(path)}  {path.relative_to(directory).as_posix()}")
    if not lines:
        raise ValueError("No release artifacts found")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n")


def stage_artifacts(source: Path, destination: Path) -> None:
    source = source.resolve(strict=True)
    destination = destination.resolve(strict=False)
    if source == destination or source in destination.parents:
        raise ValueError("Staging destination must be outside the source tree")
    destination.mkdir(parents=True, exist_ok=False)
    staged_names: set[str] = set()
    for path in sorted(source.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"Release artifacts must not contain symlinks: {path}")
        if not path.is_file():
            continue
        target_name = path.name
        if target_name in staged_names:
            raise ValueError(f"Release artifact basename collision: {target_name}")
        staged_names.add(target_name)
        shutil.copyfile(path, destination / target_name)
    if not staged_names:
        raise ValueError("No release artifacts found")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("sbom", "licenses"):
        command = subparsers.add_parser(name)
        command.add_argument("output", type=Path)
    compare = subparsers.add_parser("compare-builds")
    compare.add_argument("first", type=Path)
    compare.add_argument("second", type=Path)
    checksums = subparsers.add_parser("checksums")
    checksums.add_argument("directory", type=Path)
    checksums.add_argument("output", type=Path)
    stage = subparsers.add_parser("stage-artifacts")
    stage.add_argument("source", type=Path)
    stage.add_argument("destination", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    if args.command == "sbom":
        write_sbom(root, args.output)
    elif args.command == "licenses":
        write_license_audit(root, args.output)
    elif args.command == "compare-builds":
        compare_builds(args.first, args.second)
    elif args.command == "checksums":
        write_checksums(args.directory, args.output)
    else:
        stage_artifacts(args.source, args.destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
