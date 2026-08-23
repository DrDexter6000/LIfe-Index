from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

HOST_ENV_VARS = (
    "LIFE_INDEX_HOST_SKILL_DIR",
    "CODEX_HOME",
    "AGENTS_HOME",
    "HERMES_HOME",
    "CLAUDE_HOME",
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def _write_source(root: Path) -> None:
    (root / "references").mkdir(parents=True)
    (root / "SKILL.md").write_text(
        """---
name: life-index
triggers:
  - "/life-index"
  - "记日志"
---

# Current Skill
""",
        encoding="utf-8",
    )
    (root / "references" / "WEATHER_FLOW.md").write_text("# Weather\n", encoding="utf-8")


def _write_managed_parent_stray(skills_parent: Path, trigger: str = "/life-index parent") -> None:
    skills_parent.mkdir(parents=True, exist_ok=True)
    (skills_parent / "SKILL.md").write_text(
        f"""---
name: life-index
triggers:
  - "{trigger}"
---

# Parent Stray Skill
""",
        encoding="utf-8",
    )
    (skills_parent / "references").mkdir()
    (skills_parent / "references" / "WEATHER_FLOW.md").write_text("# Weather\n", encoding="utf-8")


def _write_unmanaged_parent_stray(skills_parent: Path) -> None:
    skills_parent.mkdir(parents=True, exist_ok=True)
    (skills_parent / "SKILL.md").write_text("# Personal Skill\n", encoding="utf-8")
    (skills_parent / "references").mkdir()
    (skills_parent / "references" / "DECOY.md").write_text("# decoy\n", encoding="utf-8")


def _isolated_subprocess_env(home: Path) -> dict[str, str]:
    env = os.environ.copy()
    for name in HOST_ENV_VARS:
        env.pop(name, None)
    env["HOME"] = str(home)
    env["USERPROFILE"] = str(home)
    return env


def test_shipped_skill_is_byte_identical_to_canonical() -> None:
    canonical_path = REPO_ROOT / "SKILL.md"
    shipped_path = REPO_ROOT / "tools" / "_skill_artifacts" / "SKILL.md"
    assert (
        canonical_path.read_bytes() == shipped_path.read_bytes()
    ), "packaged Skill artifact drifted from canonical SKILL.md"


def test_sync_skill_copies_skill_and_references_preserving_custom_triggers(tmp_path: Path) -> None:
    from tools.sync_skill import sync_skill_artifacts

    source_root = tmp_path / "checkout"
    target = tmp_path / "host" / "skills" / "life-index"
    source_root.mkdir()
    target.mkdir(parents=True)
    _write_source(source_root)
    (target / "SKILL.md").write_text(
        """---
name: life-index
triggers:
  - "/life-index"
  - "/life-index custom"
---

# Old Skill
""",
        encoding="utf-8",
    )

    payload = sync_skill_artifacts(source_root=source_root, target_dir=target)

    assert payload["success"] is True
    assert payload["data"]["status"] == "synced"
    assert payload["data"]["target_dir"] == str(target)
    assert payload["data"]["copied"] == ["SKILL.md", "references/WEATHER_FLOW.md"]
    synced_skill = (target / "SKILL.md").read_text(encoding="utf-8")
    assert "# Current Skill" in synced_skill
    assert '  - "/life-index custom"' in synced_skill
    assert (target / "references" / "WEATHER_FLOW.md").read_text(encoding="utf-8") == "# Weather\n"


def test_sync_skill_gracefully_skips_when_no_host_dir(tmp_path: Path) -> None:
    from tools.sync_skill import sync_skill_artifacts

    source_root = tmp_path / "checkout"
    source_root.mkdir()
    _write_source(source_root)

    payload = sync_skill_artifacts(source_root=source_root, target_dir=None)

    assert payload["success"] is True
    assert payload["data"]["status"] == "skipped"
    assert payload["data"]["target_dir"] is None
    assert payload["data"]["copied"] == []
    assert payload["data"]["diagnostics"][0]["code"] == "HOST_SKILL_DIR_NOT_FOUND"


def test_sync_skill_without_install_does_not_create_missing_target(tmp_path: Path) -> None:
    from tools.sync_skill import sync_skill_artifacts

    source_root = tmp_path / "checkout"
    target = tmp_path / "host" / "skills" / "life-index"
    source_root.mkdir()
    _write_source(source_root)

    payload = sync_skill_artifacts(source_root=source_root, target_dir=target)

    assert payload["success"] is True
    assert payload["data"]["status"] == "skipped"
    assert payload["data"]["delivered"] is False
    assert not target.exists()


def test_sync_skill_install_creates_host_home_target(tmp_path: Path) -> None:
    from tools.sync_skill import install_target_from_host_home, sync_skill_artifacts

    source_root = tmp_path / "checkout"
    host_home = tmp_path / ".hermes"
    target = install_target_from_host_home(host_home)
    source_root.mkdir()
    _write_source(source_root)

    payload = sync_skill_artifacts(source_root=source_root, target_dir=target, install=True)

    assert payload["success"] is True
    assert payload["data"]["status"] == "installed"
    assert payload["data"]["delivered"] is True
    assert payload["data"]["target_dir"] == str(target.resolve())
    assert payload["data"]["copied"] == ["SKILL.md", "references/WEATHER_FLOW.md"]
    assert (target / "SKILL.md").exists()
    assert (target / "references" / "WEATHER_FLOW.md").exists()


def test_sync_skill_uninstall_removes_only_managed_skill_dirs_and_preserves_data(
    tmp_path: Path,
) -> None:
    from tools.sync_skill import install_target_from_host_home, uninstall_skill_artifacts

    host_home = tmp_path / ".hermes"
    target = install_target_from_host_home(host_home)
    nested_target = host_home / "skills" / "journaling" / "life-index"
    data_dir = host_home / "Documents" / "Life-Index" / "Journals" / "2026" / "06"
    clone_dir = host_home / "src" / "life-index"
    pip_dir = host_home / "site-packages" / "life_index"
    unmanaged_skill = host_home / "skills" / "life-index-backup"
    for path in (target, nested_target, data_dir, clone_dir, pip_dir, unmanaged_skill):
        path.mkdir(parents=True)
    (target / "SKILL.md").write_text("# Life Index\n", encoding="utf-8")
    (nested_target / "SKILL.md").write_text("# Nested Life Index\n", encoding="utf-8")
    journal = data_dir / "life-index_2026-06-29_001.md"
    journal.write_text("journal data", encoding="utf-8")
    (clone_dir / "README.md").write_text("clone", encoding="utf-8")
    (pip_dir / "__init__.py").write_text("package", encoding="utf-8")
    (unmanaged_skill / "SKILL.md").write_text("backup", encoding="utf-8")

    payload = uninstall_skill_artifacts(host_home=host_home)

    assert payload["success"] is True
    assert payload["data"]["status"] == "uninstalled"
    assert sorted(payload["data"]["removed"]) == sorted(
        [str(target.resolve()), str(nested_target.resolve())]
    )
    assert not target.exists()
    assert not nested_target.exists()
    assert journal.read_text(encoding="utf-8") == "journal data"
    assert (clone_dir / "README.md").exists()
    assert (pip_dir / "__init__.py").exists()
    assert (unmanaged_skill / "SKILL.md").exists()

    second = uninstall_skill_artifacts(host_home=host_home)

    assert second["success"] is True
    assert second["data"]["status"] == "skipped"
    assert second["data"]["removed"] == []


def test_sync_skill_uninstall_dry_run_is_read_only(tmp_path: Path) -> None:
    from tools.sync_skill import install_target_from_host_home, uninstall_skill_artifacts

    host_home = tmp_path / ".codex"
    target = install_target_from_host_home(host_home)
    target.mkdir(parents=True)
    (target / "SKILL.md").write_text("# Life Index\n", encoding="utf-8")

    payload = uninstall_skill_artifacts(host_home=host_home, dry_run=True)

    assert payload["success"] is True
    assert payload["data"]["status"] == "dry_run"
    assert payload["data"]["removed"] == []
    assert payload["data"]["skipped"] == [{"path": str(target.resolve()), "reason": "dry_run"}]
    assert (target / "SKILL.md").exists()


def test_sync_skill_list_discovers_life_index_skill_dirs_without_mutation(
    tmp_path: Path,
) -> None:
    from tools.sync_skill import list_host_skill_dirs

    codex_target = tmp_path / ".codex" / "skills" / "life-index"
    hermes_nested = tmp_path / ".hermes" / "skills" / "journaling" / "life-index"
    non_matching = tmp_path / ".agents" / "skills" / "life-index-backup"
    for path in (codex_target, hermes_nested, non_matching):
        path.mkdir(parents=True)
        (path / "SKILL.md").write_text(path.name, encoding="utf-8")

    payload = list_host_skill_dirs(
        host_homes=[tmp_path / ".codex", tmp_path / ".hermes", tmp_path / ".agents"]
    )

    assert payload["success"] is True
    assert payload["data"]["status"] == "listed"
    assert sorted(payload["data"]["discovered"]) == sorted(
        [str(codex_target.resolve()), str(hermes_nested.resolve())]
    )
    assert payload["data"]["removed"] == []
    assert (codex_target / "SKILL.md").exists()
    assert (hermes_nested / "SKILL.md").exists()
    assert (non_matching / "SKILL.md").exists()


def test_sync_skill_cli_uses_host_skill_dir_env(tmp_path: Path, monkeypatch) -> None:
    source_root = tmp_path / "checkout"
    target = tmp_path / "host" / "skills" / "life-index"
    source_root.mkdir()
    target.mkdir(parents=True)
    _write_source(source_root)
    monkeypatch.setenv("LIFE_INDEX_HOST_SKILL_DIR", str(target))

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "tools.sync_skill",
            "--source-root",
            str(source_root),
            "--json",
        ],
        capture_output=True,
        text=True,
        timeout=30,
        encoding="utf-8",
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["success"] is True
    assert payload["command"] == "sync-skill"
    assert payload["data"]["status"] == "synced"
    assert payload["data"]["delivered"] is True
    assert (target / "SKILL.md").exists()


def test_sync_skill_cli_install_host_home(tmp_path: Path) -> None:
    source_root = tmp_path / "checkout"
    host_home = tmp_path / ".codex"
    target = host_home / "skills" / "life-index"
    source_root.mkdir()
    _write_source(source_root)

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "tools",
            "sync-skill",
            "--source-root",
            str(source_root),
            "--install",
            "--host-home",
            str(host_home),
            "--json",
        ],
        capture_output=True,
        text=True,
        timeout=30,
        encoding="utf-8",
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["success"] is True
    assert payload["command"] == "sync-skill"
    assert payload["data"]["status"] == "installed"
    assert payload["data"]["delivered"] is True
    assert payload["data"]["target_dir"] == str(target.resolve())
    assert (target / "SKILL.md").exists()


def test_sync_skill_cli_install_env_parent_normalizes_to_canonical_slot(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """A host skills parent is not a skill slot; install must use skills/life-index."""
    source_root = tmp_path / "checkout"
    host_home = tmp_path / ".hermes"
    skills_parent = host_home / "skills"
    canonical = skills_parent / "life-index"
    source_root.mkdir()
    canonical.mkdir(parents=True)
    _write_source(source_root)
    (canonical / "SKILL.md").write_text(
        """---
name: life-index
triggers:
  - "/life-index canonical"
---

# Existing Canonical Skill
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("LIFE_INDEX_HOST_SKILL_DIR", str(skills_parent))

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "tools",
            "sync-skill",
            "--source-root",
            str(source_root),
            "--install",
            "--json",
        ],
        capture_output=True,
        text=True,
        timeout=30,
        encoding="utf-8",
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["success"] is True
    assert payload["data"]["target_dir"] == str(canonical.resolve())
    assert payload["data"]["diagnostics"][0]["code"] == "HOST_SKILL_DIR_PARENT_NORMALIZED"
    assert not (skills_parent / "SKILL.md").exists()
    assert not (skills_parent / "references").exists()
    assert (canonical / "SKILL.md").exists()
    synced_skill = (canonical / "SKILL.md").read_text(encoding="utf-8")
    assert "# Current Skill" in synced_skill
    assert '  - "/life-index canonical"' in synced_skill


def test_sync_skill_cli_install_host_skill_dir_parent_normalizes_to_canonical_slot(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "checkout"
    host_home = tmp_path / ".hermes"
    skills_parent = host_home / "skills"
    canonical = skills_parent / "life-index"
    source_root.mkdir()
    skills_parent.mkdir(parents=True)
    _write_source(source_root)

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "tools",
            "sync-skill",
            "--source-root",
            str(source_root),
            "--install",
            "--host-skill-dir",
            str(skills_parent),
            "--json",
        ],
        capture_output=True,
        text=True,
        timeout=30,
        encoding="utf-8",
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["success"] is True
    assert payload["data"]["target_dir"] == str(canonical.resolve())
    assert payload["data"]["diagnostics"][0]["code"] == "HOST_SKILL_DIR_PARENT_NORMALIZED"
    assert not (skills_parent / "SKILL.md").exists()
    assert (canonical / "SKILL.md").exists()


def test_sync_skill_cli_install_env_parent_recovers_missing_canonical_from_managed_stray(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source_root = tmp_path / "checkout"
    host_home = tmp_path / ".hermes"
    skills_parent = host_home / "skills"
    canonical = skills_parent / "life-index"
    source_root.mkdir()
    _write_source(source_root)
    _write_managed_parent_stray(skills_parent, trigger="/life-index parent-env")
    monkeypatch.setenv("LIFE_INDEX_HOST_SKILL_DIR", str(skills_parent))

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "tools",
            "sync-skill",
            "--source-root",
            str(source_root),
            "--install",
            "--json",
        ],
        capture_output=True,
        text=True,
        timeout=30,
        encoding="utf-8",
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["success"] is True
    assert payload["data"]["status"] == "installed"
    assert payload["data"]["delivered"] is True
    assert payload["data"]["target_dir"] == str(canonical.resolve())
    assert not (skills_parent / "SKILL.md").exists()
    assert not (skills_parent / "references").exists()
    synced_skill = (canonical / "SKILL.md").read_text(encoding="utf-8")
    assert "# Current Skill" in synced_skill
    assert '  - "/life-index parent-env"' in synced_skill
    codes = [item["code"] for item in payload["data"]["diagnostics"]]
    assert "HOST_SKILL_DIR_PARENT_NORMALIZED" in codes
    assert "HOST_SKILL_DIR_PARENT_STRAY_CLEANED" in codes


def test_sync_skill_cli_install_default_home_recovers_missing_canonical_from_managed_stray(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "checkout"
    host_home = tmp_path / ".hermes"
    skills_parent = host_home / "skills"
    canonical = skills_parent / "life-index"
    source_root.mkdir()
    _write_source(source_root)
    _write_managed_parent_stray(skills_parent, trigger="/life-index parent-default")
    env = _isolated_subprocess_env(tmp_path)

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "tools",
            "sync-skill",
            "--source-root",
            str(source_root),
            "--install",
            "--json",
        ],
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
        encoding="utf-8",
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["success"] is True
    assert payload["data"]["status"] == "installed"
    assert payload["data"]["delivered"] is True
    assert payload["data"]["target_dir"] == str(canonical.resolve())
    assert not (skills_parent / "SKILL.md").exists()
    assert not (skills_parent / "references").exists()
    synced_skill = (canonical / "SKILL.md").read_text(encoding="utf-8")
    assert '  - "/life-index parent-default"' in synced_skill
    codes = [item["code"] for item in payload["data"]["diagnostics"]]
    assert "HOST_SKILL_DIR_PARENT_STRAY_RECOVERY_SELECTED" in codes
    assert "HOST_SKILL_DIR_PARENT_STRAY_CLEANED" in codes


def test_sync_skill_cli_install_default_home_does_not_guess_unmanaged_parent_stray(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "checkout"
    host_home = tmp_path / ".hermes"
    skills_parent = host_home / "skills"
    canonical = skills_parent / "life-index"
    source_root.mkdir()
    _write_source(source_root)
    _write_unmanaged_parent_stray(skills_parent)
    env = _isolated_subprocess_env(tmp_path)

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "tools",
            "sync-skill",
            "--source-root",
            str(source_root),
            "--install",
            "--json",
        ],
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
        encoding="utf-8",
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["success"] is True
    assert payload["data"]["status"] == "skipped"
    assert payload["data"]["delivered"] is False
    assert not canonical.exists()
    assert (skills_parent / "SKILL.md").read_text(encoding="utf-8") == "# Personal Skill\n"
    assert (skills_parent / "references" / "DECOY.md").exists()


def test_sync_skill_cli_non_install_env_parent_missing_canonical_does_not_create(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source_root = tmp_path / "checkout"
    host_home = tmp_path / ".hermes"
    skills_parent = host_home / "skills"
    canonical = skills_parent / "life-index"
    source_root.mkdir()
    _write_source(source_root)
    _write_managed_parent_stray(skills_parent)
    monkeypatch.setenv("LIFE_INDEX_HOST_SKILL_DIR", str(skills_parent))

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "tools",
            "sync-skill",
            "--source-root",
            str(source_root),
            "--json",
        ],
        capture_output=True,
        text=True,
        timeout=30,
        encoding="utf-8",
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["success"] is True
    assert payload["data"]["status"] == "skipped"
    assert payload["data"]["delivered"] is False
    assert not canonical.exists()
    assert (skills_parent / "SKILL.md").exists()


def test_sync_skill_refuses_non_canonical_target_without_writing_parent(
    tmp_path: Path,
) -> None:
    from tools.sync_skill import sync_skill_artifacts

    source_root = tmp_path / "checkout"
    host_home = tmp_path / ".hermes"
    skills_parent = host_home / "skills"
    canonical = skills_parent / "life-index"
    source_root.mkdir()
    canonical.mkdir(parents=True)
    _write_source(source_root)
    (canonical / "SKILL.md").write_text("# Existing Canonical\n", encoding="utf-8")

    payload = sync_skill_artifacts(source_root=source_root, target_dir=skills_parent, install=True)

    assert payload["success"] is False
    assert payload["data"]["status"] == "refused"
    assert payload["data"]["diagnostics"][0]["code"] == "HOST_SKILL_DIR_NOT_CANONICAL"
    assert not (skills_parent / "SKILL.md").exists()
    assert (canonical / "SKILL.md").read_text(encoding="utf-8") == "# Existing Canonical\n"


def test_sync_skill_refuses_life_index_leaf_outside_host_skills_layout(
    tmp_path: Path,
) -> None:
    from tools.sync_skill import sync_skill_artifacts

    source_root = tmp_path / "checkout"
    target = tmp_path / "not-a-host-slot" / "life-index"
    source_root.mkdir()
    target.mkdir(parents=True)
    _write_source(source_root)

    payload = sync_skill_artifacts(source_root=source_root, target_dir=target, install=True)

    assert payload["success"] is False
    assert payload["data"]["status"] == "refused"
    assert payload["data"]["diagnostics"][0]["code"] == "HOST_SKILL_DIR_NOT_CANONICAL"
    assert not (target / "SKILL.md").exists()


def test_sync_skill_install_recovers_managed_parent_stray_artifacts(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "checkout"
    host_home = tmp_path / ".hermes"
    skills_parent = host_home / "skills"
    canonical = skills_parent / "life-index"
    source_root.mkdir()
    _write_source(source_root)
    _write_managed_parent_stray(skills_parent)

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "tools",
            "sync-skill",
            "--source-root",
            str(source_root),
            "--install",
            "--host-home",
            str(host_home),
            "--json",
        ],
        capture_output=True,
        text=True,
        timeout=30,
        encoding="utf-8",
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["success"] is True
    assert payload["data"]["target_dir"] == str(canonical.resolve())
    assert not (skills_parent / "SKILL.md").exists()
    assert not (skills_parent / "references").exists()
    synced_skill = (canonical / "SKILL.md").read_text(encoding="utf-8")
    assert "# Current Skill" in synced_skill
    assert '  - "/life-index parent"' in synced_skill
    codes = [item["code"] for item in payload["data"]["diagnostics"]]
    assert "HOST_SKILL_DIR_PARENT_STRAY_CLEANED" in codes


def test_sync_skill_install_preserves_unmanaged_parent_stray_artifacts(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "checkout"
    host_home = tmp_path / ".hermes"
    skills_parent = host_home / "skills"
    canonical = skills_parent / "life-index"
    source_root.mkdir()
    _write_source(source_root)
    _write_unmanaged_parent_stray(skills_parent)

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "tools",
            "sync-skill",
            "--source-root",
            str(source_root),
            "--install",
            "--host-home",
            str(host_home),
            "--json",
        ],
        capture_output=True,
        text=True,
        timeout=30,
        encoding="utf-8",
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["success"] is True
    assert (skills_parent / "SKILL.md").read_text(encoding="utf-8") == "# Personal Skill\n"
    assert (skills_parent / "references" / "DECOY.md").exists()
    assert (canonical / "SKILL.md").exists()
    codes = [item["code"] for item in payload["data"]["diagnostics"]]
    assert "HOST_SKILL_DIR_PARENT_STRAY_PRESERVED" in codes


def test_sync_skill_default_source_root_falls_back_to_packaged_artifacts(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Wheel installs must deliver SKILL.md without a checkout root beside tools."""
    import tools.sync_skill.__main__ as sync_main
    from tools.sync_skill import sync_skill_artifacts

    fake_installed_main = (
        tmp_path / "venv" / "Lib" / "site-packages" / "tools" / "sync_skill" / "__main__.py"
    )
    fake_installed_main.parent.mkdir(parents=True)
    fake_installed_main.write_text("# installed entrypoint placeholder\n", encoding="utf-8")
    cwd_without_skill = tmp_path / "cwd"
    cwd_without_skill.mkdir()
    target = tmp_path / ".codex" / "skills" / "life-index"
    monkeypatch.setattr(sync_main, "__file__", str(fake_installed_main))
    monkeypatch.chdir(cwd_without_skill)

    payload = sync_skill_artifacts(
        source_root=sync_main._default_source_root(),
        target_dir=target,
        install=True,
    )

    assert payload["success"] is True
    assert payload["data"]["status"] == "installed"
    assert payload["data"]["delivered"] is True
    assert "SKILL.md" in payload["data"]["copied"]
    assert (target / "SKILL.md").is_file()
    assert sorted(path.name for path in (target / "references").glob("*.md")) == [
        "ENTITY_MAINTENANCE_PLAYBOOK.md",
        "GROUNDED_QUERY_PLAYBOOK.md",
        "PHOTO_IMPORT_REVIEW_PLAYBOOK.md",
        "WEATHER_FLOW.md",
    ]


def test_sync_skill_default_source_root_ignores_cwd_decoy_in_installed_layout(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Implicit source roots must not trust cwd; use --source-root for custom sources."""
    import tools.sync_skill.__main__ as sync_main
    from tools.sync_skill import sync_skill_artifacts

    fake_installed_main = (
        tmp_path / "venv" / "Lib" / "site-packages" / "tools" / "sync_skill" / "__main__.py"
    )
    fake_installed_main.parent.mkdir(parents=True)
    fake_installed_main.write_text("# installed entrypoint placeholder\n", encoding="utf-8")
    decoy_cwd = tmp_path / "decoy-cwd"
    decoy_cwd.mkdir()
    (decoy_cwd / "SKILL.md").write_text("# Decoy Skill\n", encoding="utf-8")
    (decoy_cwd / "references").mkdir()
    (decoy_cwd / "references" / "DECOY.md").write_text("# decoy\n", encoding="utf-8")
    target = tmp_path / ".codex" / "skills" / "life-index"
    monkeypatch.setattr(sync_main, "__file__", str(fake_installed_main))
    monkeypatch.chdir(decoy_cwd)

    source_root = sync_main._default_source_root()
    payload = sync_skill_artifacts(source_root=source_root, target_dir=target, install=True)

    assert source_root.name == "_skill_artifacts"
    assert payload["success"] is True
    assert payload["data"]["delivered"] is True
    installed_skill = (target / "SKILL.md").read_text(encoding="utf-8")
    assert "# Decoy Skill" not in installed_skill
    assert installed_skill == (source_root / "SKILL.md").read_text(encoding="utf-8")
    assert not (target / "references" / "DECOY.md").exists()
    assert (target / "references" / "GROUNDED_QUERY_PLAYBOOK.md").is_file()


def test_sync_skill_cli_install_dry_run_reports_nested_duplicate_without_mutation(
    tmp_path: Path,
) -> None:
    """UF-2: install dry-run previews nested duplicate cleanup without deleting files."""
    source_root = tmp_path / "checkout"
    host_home = tmp_path / ".codex"
    canonical = host_home / "skills" / "life-index"
    nested = canonical / "life-index"
    source_root.mkdir()
    nested.mkdir(parents=True)
    _write_source(source_root)
    (nested / "SKILL.md").write_text(
        """---
name: life-index
triggers:
  - "/life-index nested"
---

# Nested Skill
""",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "tools",
            "sync-skill",
            "--source-root",
            str(source_root),
            "--install",
            "--host-home",
            str(host_home),
            "--dry-run",
            "--json",
        ],
        capture_output=True,
        text=True,
        timeout=30,
        encoding="utf-8",
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["success"] is True
    assert payload["data"]["status"] == "dry_run"
    assert payload["data"]["delivered"] is False
    assert payload["data"]["dedupe"]["status"] == "would_remove"
    assert payload["data"]["dedupe"]["nested_dir"] == str(nested.resolve())
    assert not (canonical / "SKILL.md").exists()
    assert (nested / "SKILL.md").exists()


def test_sync_skill_install_collapses_nested_duplicate_preserving_custom_triggers(
    tmp_path: Path,
) -> None:
    """UF-2: install converges skills/life-index/life-index to the canonical slot."""
    from tools.sync_skill import install_target_from_host_home, sync_skill_artifacts

    source_root = tmp_path / "checkout"
    host_home = tmp_path / ".codex"
    target = install_target_from_host_home(host_home)
    nested = target / "life-index"
    source_root.mkdir()
    nested.mkdir(parents=True)
    _write_source(source_root)
    (nested / "SKILL.md").write_text(
        """---
name: life-index
triggers:
  - "/life-index nested"
---

# Nested Skill
""",
        encoding="utf-8",
    )
    (nested / "references").mkdir()
    (nested / "references" / "OLD.md").write_text("# old\n", encoding="utf-8")

    payload = sync_skill_artifacts(source_root=source_root, target_dir=target, install=True)

    assert payload["success"] is True
    assert payload["data"]["status"] == "installed"
    assert payload["data"]["dedupe"]["status"] == "removed"
    assert payload["data"]["dedupe"]["nested_dir"] == str(nested.resolve())
    assert (target / "SKILL.md").exists()
    assert not nested.exists()
    synced_skill = (target / "SKILL.md").read_text(encoding="utf-8")
    assert "# Current Skill" in synced_skill
    assert '  - "/life-index nested"' in synced_skill


def test_sync_skill_cli_install_auto_converges_managed_nested_duplicate(
    tmp_path: Path,
) -> None:
    """Install without explicit dir converges canonical + managed nested duplicate."""
    source_root = tmp_path / "checkout"
    host_home = tmp_path / ".hermes"
    canonical = host_home / "skills" / "life-index"
    nested = canonical / "life-index"
    source_root.mkdir()
    canonical.mkdir(parents=True)
    nested.mkdir(parents=True)
    _write_source(source_root)
    (canonical / "SKILL.md").write_text(
        """---
name: life-index
triggers:
  - "/life-index canonical"
---

# Canonical Skill
""",
        encoding="utf-8",
    )
    (nested / "SKILL.md").write_text(
        """---
name: life-index
triggers:
  - "/life-index nested"
---

# Nested Skill
""",
        encoding="utf-8",
    )
    (nested / "references").mkdir()
    (nested / "references" / "OLD.md").write_text("# old\n", encoding="utf-8")
    env = _isolated_subprocess_env(tmp_path)

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "tools",
            "sync-skill",
            "--source-root",
            str(source_root),
            "--install",
            "--json",
        ],
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
        encoding="utf-8",
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["success"] is True
    assert payload["data"]["status"] == "synced"
    assert payload["data"]["target_dir"] == str(canonical.resolve())
    assert payload["data"]["dedupe"]["status"] == "removed"
    assert payload["data"]["dedupe"]["nested_dir"] == str(nested.resolve())
    assert not nested.exists()
    synced_skill = (canonical / "SKILL.md").read_text(encoding="utf-8")
    assert "# Current Skill" in synced_skill
    assert '  - "/life-index canonical"' in synced_skill
    assert '  - "/life-index nested"' in synced_skill
    diagnostics = payload["data"]["diagnostics"]
    assert diagnostics[0]["code"] == "HOST_SKILL_DIR_NESTED_DUPLICATE_AUTOCONVERGED"
    assert str(canonical.resolve()) in diagnostics[0]["message"]
    assert str(nested.resolve()) in diagnostics[0]["message"]


def test_sync_skill_cli_install_refuses_autoconverge_for_unmanaged_nested_content(
    tmp_path: Path,
) -> None:
    """Nested duplicates with extra user content remain fail-closed and untouched."""
    source_root = tmp_path / "checkout"
    host_home = tmp_path / ".hermes"
    canonical = host_home / "skills" / "life-index"
    nested = canonical / "life-index"
    source_root.mkdir()
    canonical.mkdir(parents=True)
    nested.mkdir(parents=True)
    _write_source(source_root)
    (canonical / "SKILL.md").write_text("# Canonical Skill\n", encoding="utf-8")
    (nested / "SKILL.md").write_text("# Nested Skill\n", encoding="utf-8")
    user_note = nested / "notes.md"
    user_note.write_text("user content", encoding="utf-8")
    env = _isolated_subprocess_env(tmp_path)

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "tools",
            "sync-skill",
            "--source-root",
            str(source_root),
            "--install",
            "--json",
        ],
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
        encoding="utf-8",
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["success"] is True
    assert payload["data"]["status"] == "skipped"
    assert payload["data"]["delivered"] is False
    assert payload["data"]["diagnostics"][0]["code"] == "HOST_SKILL_DIR_AMBIGUOUS"
    assert nested.exists()
    assert user_note.read_text(encoding="utf-8") == "user content"
    assert (canonical / "SKILL.md").read_text(encoding="utf-8") == "# Canonical Skill\n"


def test_sync_skill_reports_playbook_unchanged_with_changelog_pointer(
    tmp_path: Path,
) -> None:
    """UF-3: upgrade path reports when code changed but playbook did not."""
    source_root = tmp_path / "checkout"
    target = tmp_path / "host" / "skills" / "life-index"
    source_root.mkdir()
    target.mkdir(parents=True)
    _write_source(source_root)
    (target / "SKILL.md").write_text(
        (source_root / "SKILL.md").read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "tools",
            "sync-skill",
            "--source-root",
            str(source_root),
            "--host-skill-dir",
            str(target),
        ],
        capture_output=True,
        text=True,
        timeout=30,
        encoding="utf-8",
    )

    assert result.returncode == 0, result.stderr
    assert "playbook unchanged; changelog: CHANGELOG.md" in result.stdout


def test_sync_skill_cli_uninstall_host_home_roundtrip(tmp_path: Path) -> None:
    source_root = tmp_path / "checkout"
    host_home = tmp_path / ".hermes"
    target = host_home / "skills" / "life-index"
    source_root.mkdir()
    _write_source(source_root)

    install = subprocess.run(
        [
            sys.executable,
            "-m",
            "tools",
            "sync-skill",
            "--source-root",
            str(source_root),
            "--install",
            "--host-home",
            str(host_home),
            "--json",
        ],
        capture_output=True,
        text=True,
        timeout=30,
        encoding="utf-8",
    )
    assert install.returncode == 0, install.stderr
    assert (target / "SKILL.md").exists()

    uninstall = subprocess.run(
        [
            sys.executable,
            "-m",
            "tools",
            "sync-skill",
            "--uninstall",
            "--host-home",
            str(host_home),
            "--json",
        ],
        capture_output=True,
        text=True,
        timeout=30,
        encoding="utf-8",
    )

    assert uninstall.returncode == 0, uninstall.stderr
    payload = json.loads(uninstall.stdout)
    assert payload["success"] is True
    assert payload["data"]["status"] == "uninstalled"
    assert payload["data"]["removed"] == [str(target.resolve())]
    assert not target.exists()


def test_sync_skill_cli_list_is_read_only_across_default_host_homes(
    tmp_path: Path,
) -> None:
    codex_target = tmp_path / ".codex" / "skills" / "life-index"
    hermes_nested = tmp_path / ".hermes" / "skills" / "journaling" / "life-index"
    for path in (codex_target, hermes_nested):
        path.mkdir(parents=True)
        (path / "SKILL.md").write_text(path.name, encoding="utf-8")
    env = _isolated_subprocess_env(tmp_path)

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "tools",
            "sync-skill",
            "--list",
            "--json",
        ],
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
        encoding="utf-8",
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["success"] is True
    assert sorted(payload["data"]["discovered"]) == sorted(
        [str(codex_target.resolve()), str(hermes_nested.resolve())]
    )
    assert (codex_target / "SKILL.md").exists()
    assert (hermes_nested / "SKILL.md").exists()


def test_sync_skill_cli_uninstall_without_explicit_target_is_refused(tmp_path: Path) -> None:
    env = _isolated_subprocess_env(tmp_path)

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "tools",
            "sync-skill",
            "--uninstall",
            "--json",
        ],
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
        encoding="utf-8",
    )

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["success"] is False
    assert payload["data"]["status"] == "refused"
    assert payload["data"]["diagnostics"][0]["code"] == "UNINSTALL_REQUIRES_HOST_HOME"


def test_sync_skill_cli_conflicting_actions_are_refused(tmp_path: Path) -> None:
    host_home = tmp_path / ".hermes"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "tools",
            "sync-skill",
            "--list",
            "--uninstall",
            "--host-home",
            str(host_home),
            "--json",
        ],
        capture_output=True,
        text=True,
        timeout=30,
        encoding="utf-8",
    )

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["success"] is False
    assert payload["data"]["status"] == "refused"
    assert payload["data"]["diagnostics"][0]["code"] == "SYNC_SKILL_ACTION_CONFLICT"


def test_find_host_skill_dir_detects_nested_hermes_skill_dir(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import tools.sync_skill as sync_skill

    target = tmp_path / ".hermes" / "skills" / "productivity" / "life-index"
    target.mkdir(parents=True)
    monkeypatch.setattr(sync_skill.Path, "home", lambda: tmp_path)
    for name in (
        "LIFE_INDEX_HOST_SKILL_DIR",
        "CODEX_HOME",
        "AGENTS_HOME",
        "HERMES_HOME",
        "CLAUDE_HOME",
    ):
        monkeypatch.delenv(name, raising=False)

    found, diagnostics = sync_skill.find_host_skill_dir()

    assert found == target
    assert diagnostics == []


def test_find_host_skill_dir_reports_ambiguous_nested_matches(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import tools.sync_skill as sync_skill

    first = tmp_path / ".hermes" / "skills" / "productivity" / "life-index"
    second = tmp_path / ".claude" / "skills" / "journaling" / "life-index"
    first.mkdir(parents=True)
    second.mkdir(parents=True)
    monkeypatch.setattr(sync_skill.Path, "home", lambda: tmp_path)
    for name in (
        "LIFE_INDEX_HOST_SKILL_DIR",
        "CODEX_HOME",
        "AGENTS_HOME",
        "HERMES_HOME",
        "CLAUDE_HOME",
    ):
        monkeypatch.delenv(name, raising=False)

    found, diagnostics = sync_skill.find_host_skill_dir()

    assert found is None
    assert diagnostics[0]["code"] == "HOST_SKILL_DIR_AMBIGUOUS"
    assert str(first) in diagnostics[0]["message"]
    assert str(second) in diagnostics[0]["message"]


def test_sync_skill_cli_loudly_reports_undelivered_when_no_host_dir(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "checkout"
    source_root.mkdir()
    _write_source(source_root)
    env = _isolated_subprocess_env(tmp_path)

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "tools.sync_skill",
            "--source-root",
            str(source_root),
            "--json",
        ],
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
        encoding="utf-8",
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["success"] is True
    assert payload["data"]["status"] == "skipped"
    assert payload["data"]["delivered"] is False
    assert payload["data"]["diagnostics"][0]["code"] == "HOST_SKILL_DIR_NOT_FOUND"
