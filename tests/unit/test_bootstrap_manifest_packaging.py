"""Packaging contract for bootstrap manifest runtime availability."""

from __future__ import annotations

import importlib
import json
import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGED_SKILL_ROOT = REPO_ROOT / "tools" / "_skill_artifacts"


def _root_manifest() -> dict[str, object]:
    return json.loads((REPO_ROOT / "bootstrap-manifest.json").read_text(encoding="utf-8"))


def test_tools_package_contains_bootstrap_manifest_resource() -> None:
    """Wheel installs must carry a manifest inside the importable tools package."""
    tools_package = importlib.import_module("tools")
    package_dirs = [
        Path(raw_path) for raw_path in tools_package.__path__ if Path(raw_path).is_dir()
    ]
    resources = [package_dir / "bootstrap-manifest.json" for package_dir in package_dirs]
    resource = next((candidate for candidate in resources if candidate.is_file()), None)

    assert resource is not None
    packaged = json.loads(resource.read_text(encoding="utf-8"))
    assert packaged == _root_manifest()


def test_read_bootstrap_manifest_falls_back_to_packaged_resource(tmp_path, monkeypatch) -> None:
    """Installed wheels do not have the repo-root manifest path beside tools."""
    import tools.__main__ as cli_main

    monkeypatch.setattr(cli_main, "BOOTSTRAP_MANIFEST_PATH", tmp_path / "missing.json")

    assert cli_main.read_bootstrap_manifest() == _root_manifest()


def test_packaging_config_declares_bootstrap_manifest_data() -> None:
    """Setuptools config must include the package resource in built wheels."""
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    setuptools_config = pyproject["tool"]["setuptools"]
    package_data = setuptools_config["package-data"]

    assert setuptools_config["include-package-data"] is True
    assert "bootstrap-manifest.json" in package_data["tools"]
    assert "_skill_artifacts/SKILL.md" in package_data["tools"]
    assert "_skill_artifacts/references/*.md" in package_data["tools"]


def test_packaged_skill_artifacts_match_root_skill_sources() -> None:
    """Root SKILL.md and references remain the development SSOT."""
    assert (PACKAGED_SKILL_ROOT / "SKILL.md").read_bytes() == (REPO_ROOT / "SKILL.md").read_bytes()

    root_references = sorted(
        path.relative_to(REPO_ROOT / "references")
        for path in (REPO_ROOT / "references").rglob("*.md")
    )
    packaged_references = sorted(
        path.relative_to(PACKAGED_SKILL_ROOT / "references")
        for path in (PACKAGED_SKILL_ROOT / "references").rglob("*.md")
    )
    assert packaged_references == root_references
    for relative_path in root_references:
        assert (PACKAGED_SKILL_ROOT / "references" / relative_path).read_bytes() == (
            REPO_ROOT / "references" / relative_path
        ).read_bytes()


def test_built_wheel_contains_packaged_skill_artifacts(tmp_path: Path) -> None:
    """PyPI wheels must carry sync-skill artifacts in an importable package path."""
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "wheel",
            str(REPO_ROOT),
            "--no-deps",
            "--wheel-dir",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        timeout=120,
        encoding="utf-8",
    )
    assert result.returncode == 0, result.stderr
    wheel = next(tmp_path.glob("life_index-*.whl"))

    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())

    assert "tools/_skill_artifacts/SKILL.md" in names
    for relative_path in (REPO_ROOT / "references").rglob("*.md"):
        wheel_path = (
            Path("tools")
            / "_skill_artifacts"
            / "references"
            / relative_path.relative_to(REPO_ROOT / "references")
        )
        assert wheel_path.as_posix() in names


def test_root_and_packaged_manifest_declare_skill_artifacts() -> None:
    root_manifest = _root_manifest()
    packaged_manifest = json.loads(
        (REPO_ROOT / "tools" / "bootstrap-manifest.json").read_text(encoding="utf-8")
    )

    assert root_manifest["skill_artifacts"] == ["SKILL.md", "references/"]
    assert packaged_manifest["skill_artifacts"] == root_manifest["skill_artifacts"]


def test_manifest_in_includes_bootstrap_manifest_sources() -> None:
    """sdist inputs must include both the root authority file and package copy."""
    manifest_in = (REPO_ROOT / "MANIFEST.in").read_text(encoding="utf-8")

    assert "include bootstrap-manifest.json" in manifest_in
    assert "include tools/bootstrap-manifest.json" in manifest_in
    assert "include SKILL.md" in manifest_in
    assert "recursive-include references *.md" in manifest_in
    assert "include tools/_skill_artifacts/SKILL.md" in manifest_in
    assert "recursive-include tools/_skill_artifacts/references *.md" in manifest_in
