"""Safety checks for agent-facing onboarding instructions."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _read(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def test_onboarding_is_bootstrap_driven_one_page() -> None:
    onboarding = _read("AGENT_ONBOARDING.md")

    assert len(onboarding.splitlines()) <= 140
    assert "life-index bootstrap --json" in onboarding
    assert "safe_next_steps" in onboarding
    assert "needs_human" in onboarding
    assert "Step 4.1" not in onboarding
    assert "Step 5.3" not in onboarding
    assert "CLI Quick Reference" not in onboarding


def test_onboarding_forbids_waiting_for_semantic_ready() -> None:
    # whitespace-normalized so assertions survive doc line-wrapping
    onboarding = " ".join(_read("AGENT_ONBOARDING.md").split())

    assert "no semantic/vector indexing to wait for" in onboarding
    assert "keyword readiness is all onboarding needs" in onboarding


def test_onboarding_data_safety_rule_stays_visible() -> None:
    onboarding = _read("AGENT_ONBOARDING.md")

    assert "Never delete" in onboarding
    assert "~/Documents/Life-Index" in onboarding
    assert "fresh install" in onboarding


def test_clean_replacement_validation_uses_exact_new_venv_entries() -> None:
    onboarding = _read("AGENT_ONBOARDING.md")
    assert "### 3A. Program replacement validation" in onboarding
    assert "### 3B. Host integration and skill delivery" in onboarding
    validation = onboarding.split("### 3A. Program replacement validation", 1)[1].split(
        "### 3B. Host integration and skill delivery", 1
    )[0]

    assert '"$NEW_ROOT/.venv/bin/python" -m pip install -e "$NEW_ROOT"' in validation
    assert '"$NEW_ROOT/.venv/bin/life-index" bootstrap --json' in validation
    assert (
        '& (Join-Path $NewRoot ".venv\\Scripts\\python.exe") -m pip install -e $NewRoot'
        in validation
    )
    assert '& (Join-Path $NewRoot ".venv\\Scripts\\life-index.exe") bootstrap --json' in validation
    assert "python -m tools bootstrap --json" not in validation


def test_clean_replacement_validation_isolates_cwd_pythonpath_and_data() -> None:
    onboarding = _read("AGENT_ONBOARDING.md")
    assert "### 3A. Program replacement validation" in onboarding
    assert "### 3B. Host integration and skill delivery" in onboarding
    validation = onboarding.split("### 3A. Program replacement validation", 1)[1].split(
        "### 3B. Host integration and skill delivery", 1
    )[0]

    assert 'NEUTRAL_CWD="$(mktemp -d)"' in validation
    assert 'cd "$NEUTRAL_CWD"' in validation
    assert 'env -u PYTHONPATH LIFE_INDEX_DATA_DIR="$SANDBOX_DATA"' in validation
    assert "$NeutralCwd = Join-Path" in validation
    assert "Set-Location $NeutralCwd" in validation
    assert "Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue" in validation
    assert "$env:LIFE_INDEX_DATA_DIR = $SandboxData" in validation


def test_clean_replacement_uses_stable_operator_selected_program_root() -> None:
    onboarding = _read("AGENT_ONBOARDING.md")
    validation = onboarding.split("### 3A. Program replacement validation", 1)[1].split(
        "### 3B. Host integration and skill delivery", 1
    )[0]

    assert 'NEW_ROOT="<new-target>/life-index"' in validation
    assert 'NEW_ROOT="$(mktemp -d)/life-index"' not in validation
    assert '$NewRoot = Join-Path "<new-target>" "life-index"' in validation
    assert "$NewRoot = Join-Path ([IO.Path]::GetTempPath())" not in validation
    assert validation.count('="$(mktemp -d)"') == 2
    assert validation.count("[IO.Path]::GetTempPath()") == 2
    assert validation.count("[guid]::NewGuid()") == 2


def test_windows_replacement_uses_operator_selected_supported_python_launcher() -> None:
    onboarding = _read("AGENT_ONBOARDING.md")
    validation = onboarding.split("### 3A. Program replacement validation", 1)[1].split(
        "### 3B. Host integration and skill delivery", 1
    )[0]

    assert '$PythonExe = "<path-to-supported-python.exe>"' in validation
    assert (
        "& $PythonExe -c 'import sys; assert sys.version_info >= (3, 11), "
        'f"Python >=3.11 required, got {sys.version}"\''
    ) in validation
    assert '& $PythonExe -m venv (Join-Path $NewRoot ".venv")' in validation
    assert "py -3.11" not in validation


def test_host_integration_is_standalone_and_uses_isolated_posix_launcher() -> None:
    onboarding = _read("AGENT_ONBOARDING.md")
    host_integration = onboarding.split("### 3B. Host integration and skill delivery", 1)[1].split(
        "### 3C. Owner-authorized data maintenance", 1
    )[0]
    posix = host_integration.split("Windows PowerShell:", 1)[0]

    assert 'NEW_ROOT="<new-target>/life-index"' in posix
    assert 'HOST_HOME="<host-home>"' in posix
    commands = (
        'env -u PYTHONPATH "$NEW_ROOT/.venv/bin/life-index" sync-skill --list --json',
        'env -u PYTHONPATH "$NEW_ROOT/.venv/bin/life-index" sync-skill --install '
        '--host-home "$HOST_HOME" --dry-run --json',
        'env -u PYTHONPATH "$NEW_ROOT/.venv/bin/life-index" sync-skill --install '
        '--host-home "$HOST_HOME" --json',
        'env -u PYTHONPATH "$NEW_ROOT/.venv/bin/life-index" sync-skill --uninstall '
        '--host-home "$HOST_HOME" --json',
    )
    for command in commands:
        assert command in posix
    assert posix.count('env -u PYTHONPATH "$NEW_ROOT/.venv/bin/life-index" sync-skill') == 4


def test_host_integration_is_standalone_and_uses_isolated_windows_launcher() -> None:
    onboarding = _read("AGENT_ONBOARDING.md")
    host_integration = onboarding.split("### 3B. Host integration and skill delivery", 1)[1].split(
        "### 3C. Owner-authorized data maintenance", 1
    )[0]
    windows = host_integration.split("Windows PowerShell:", 1)[1]

    assert '$NewRoot = Join-Path "<new-target>" "life-index"' in windows
    assert '$HostHome = "<host-home>"' in windows
    assert '$LifeIndex = Join-Path $NewRoot ".venv\\Scripts\\life-index.exe"' in windows
    assert "Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue" in windows
    commands = (
        "& $LifeIndex sync-skill --list --json",
        "& $LifeIndex sync-skill --install --host-home $HostHome --dry-run --json",
        "& $LifeIndex sync-skill --install --host-home $HostHome --json",
        "& $LifeIndex sync-skill --uninstall --host-home $HostHome --json",
    )
    for command in commands:
        assert command in windows
    assert windows.count("& $LifeIndex sync-skill") == 4


def test_onboarding_separates_program_host_and_data_lifecycles() -> None:
    onboarding = _read("AGENT_ONBOARDING.md")

    assert "### 3A. Program replacement validation" in onboarding
    assert "### 3B. Host integration and skill delivery" in onboarding
    assert "### 3C. Owner-authorized data maintenance" in onboarding
    assert (
        "Host integration is a separate cutover action and is not evidence that program "
        "replacement is valid."
    ) in " ".join(onboarding.split())
    assert (
        "A bootstrap plan obtained against a real data root is a separate "
        "data-maintenance plan. Never execute it merely to accept program replacement."
    ) in " ".join(onboarding.split())
    maintenance = onboarding.split("### 3C. Owner-authorized data maintenance", 1)[1].split(
        "## 4. Execute The Bootstrap Plan", 1
    )[0]
    assert "migrate" in maintenance
    assert "index --rebuild" in maintenance


def test_existing_program_upgrade_starts_with_atomic_upgrade_not_bootstrap() -> None:
    onboarding = " ".join(_read("AGENT_ONBOARDING.md").split())
    skill = " ".join(_read("SKILL.md").split())
    api = " ".join(_read("docs/API.md").split())

    assert "Existing program upgrade starts with `life-index upgrade --plan --json`." in onboarding
    assert "Do not use `bootstrap` as the program-upgrade command." in onboarding
    assert (
        "Bootstrap is for first-install and separately authorized data lifecycle planning."
        in onboarding
    )
    assert "已有程序升级只运行 `life-index upgrade --plan --json`" in skill
    assert "不得把 `bootstrap` 当作程序升级命令" in skill
    assert "neutral temporary working directory" in api
    assert "synthetic data directory" in api
    assert "cleared `PYTHONPATH`" in api


def test_skill_explains_packaged_authority_without_skill_leaf_guessing() -> None:
    skill = " ".join(_read("SKILL.md").split())

    assert "`life-index version` 返回安装包内嵌的 authority manifest" in skill
    assert "不要在已安装 Skill 目录中猜找 `bootstrap-manifest.json`" in skill


def test_onboarding_and_bootstrap_forbid_destructive_recovery_guidance() -> None:
    public_guidance = "\n".join(
        _read(path) for path in ("AGENT_ONBOARDING.md", "SKILL.md", "docs/API.md")
    )
    api = _read("docs/API.md")
    bootstrap_source = _read("tools/bootstrap/__init__.py")

    assert "git checkout -- ." not in public_guidance
    assert "Delete and reclone" not in public_guidance
    assert 'suggested_command: "git --no-optional-locks status --short"' in api
    assert 'suggested_command: "git status --short"' not in api
    assert '["fetch"' not in bootstrap_source
    assert "git fetch --quiet" not in public_guidance


def test_onboarding_documents_reversible_skill_install_safety() -> None:
    onboarding = _read("AGENT_ONBOARDING.md")

    assert "sync-skill --list --json" in onboarding
    assert "sync-skill --uninstall" in onboarding
    assert "only removes agent skill artifacts" in onboarding
    assert "never deletes journals" in onboarding


def test_onboarding_explains_cli_gui_host_agent_relationship() -> None:
    onboarding = _read("AGENT_ONBOARDING.md")

    assert "System Overview" in onboarding
    assert (
        "Life Index is a deterministic toolset for a host agent, not a standalone "
        "human-facing intelligent app."
    ) in onboarding
    assert "CLI (life-index) is the deterministic tool layer" in onboarding
    assert "Host agent (for example, Hermes) is the intelligence layer." in onboarding
    assert "GUI is the optional UX layer over the same CLI-backed capabilities." in onboarding
    assert "Data stays separate from program code." in onboarding


def test_readme_does_not_reference_real_first_entry_smoke_file() -> None:
    readme = _read("README.md")
    readme_en = _read("README.en.md")
    skill = _read("SKILL.md")
    onboarding = _read("AGENT_ONBOARDING.md")

    assert "first-entry.json" not in readme
    assert "first-entry.json" not in readme_en
    assert "first-entry.json" not in skill
    assert "sandbox" in onboarding.lower()
    assert "LIFE_INDEX_DATA_DIR" in onboarding


def test_readme_uses_public_synthetic_and_advisory_eval_truth() -> None:
    readme = _read("README.md")
    readme_en = _read("README.en.md")

    for text in (readme, readme_en):
        assert "2,400+ unit tests" not in text
        assert "keyword-only Recall@5 = **0.7857**" not in text
        assert "4,200+ pytest-collected tests" in text
        assert "108-query" not in text
        assert "Recall@5 = **0.9231**" not in text
        assert "synthetic token-match blocker" in text
        assert "advisory evidence" in text


def test_readme_current_version_points_to_release_ssot() -> None:
    readme = _read("README.md")
    readme_en = _read("README.en.md")

    assert "当前稳定线（" not in readme
    assert "current stable line (" not in readme_en
    assert "life-index --version" in readme
    assert "life-index --version" in readme_en
    assert "CHANGELOG.md" in readme
    assert "CHANGELOG.md" in readme_en


def test_skill_uses_progressive_disclosure_for_grounded_query_playbook() -> None:
    skill = _read("SKILL.md")
    playbook = _read("references/GROUNDED_QUERY_PLAYBOOK.md")
    playbook_link = "[Full grounded query playbook](references/GROUNDED_QUERY_PLAYBOOK.md)"

    assert len(skill.splitlines()) <= 590
    assert "references/GROUNDED_QUERY_PLAYBOOK.md" in skill
    assert "Full grounded query playbook" in skill
    assert skill.count(playbook_link) == 2
    assert "`references/GROUNDED_QUERY_PLAYBOOK.md`" not in skill
    assert "life-index journal batch-get" in playbook
    assert "answer.insights[]" in playbook
    assert "ensure` -> `discover` -> `navigate" in playbook


def test_grounded_query_playbook_keeps_magazine_output_conditional() -> None:
    playbook = " ".join(_read("references/GROUNDED_QUERY_PLAYBOOK.md").split())

    assert (
        "time-scoped evidence, facet/count/enumeration answers, cross-facet questions, "
        "magazine-style analysis" in playbook
    )
    assert "Only for magazine-style analysis or an explicit grounded-status request" in playbook
    assert (
        "Ordinary count, facet, enumeration, cross-facet, and time-scoped answers use "
        "bounded evidence and honest uncertainty without requiring `answer.insights[]` or a "
        "`GROUNDED` / `PARTIAL` / `UNGROUNDED` status." in playbook
    )


def test_skill_session_surface_mentions_upgrade_freshness_signal() -> None:
    skill = _read("SKILL.md")

    assert "life-index health --json" in skill
    assert "upgrade_freshness" in skill
    assert "只运行该只读 `life-index upgrade --plan --json` 指针" in skill


def test_skill_teaches_upgrade_atom_before_apply() -> None:
    skill = _read("SKILL.md")

    assert "life-index upgrade --plan --json" in skill
    assert "UPGRADE_REINSTALL_REQUIRED" in skill
    assert "AGENT_ONBOARDING.md" in skill
    assert "现有环境、checkout 与用户数据不动" in skill


def test_skill_teaches_host_agent_ops_discipline() -> None:
    skill = _read("SKILL.md")
    playbook = _read("references/ENTITY_MAINTENANCE_PLAYBOOK.md")

    assert "运维纪律" in skill
    assert "dedicated install" in skill
    assert "只读诊断" in skill
    assert "运维纪律" in playbook


def test_skill_entity_interview_teaches_agent_recommend_user_confirm_write() -> None:
    skill = _read("SKILL.md")

    assert "筛 → 荐 → 问 → 写" in skill
    assert "按 `evidence` 指针读原文" in skill
    assert "带理由建议" in skill
    assert "批量授权" in skill
    assert "队列外" in skill
    assert "写入必须有人判" in skill
    assert "life-index entity --review --action add_relationship" in skill
    assert "life-index entity --unmerge" in skill


def test_skill_entity_reference_teaches_workflow_facades_not_update_shortcut() -> None:
    skill = _read("SKILL.md")

    assert "life-index entity build --from-journals --preview --json" in skill
    assert "life-index entity profile --id ENTITY_ID --json" in skill
    assert "life-index abstract --entities --json" in skill
    assert "life-index abstract --entities --id ENTITY_ID --json" in skill
    assert "life-index entity audit --json" in skill
    assert "life-index entity maintain --normalize --preview --json" in skill
    assert "life-index entity maintain --delete --id ENTITY_ID --preview --json" in skill
    assert "life-index entity --list|--add|--resolve|--update" not in skill
    for retired in (
        "life-index entity --seed",
        "life-index entity --merge",
        "life-index entity --delete",
        "life-index entity --update",
    ):
        assert retired not in skill


def test_skill_and_entity_playbook_teach_profile_docs_payoff_path() -> None:
    skill = _read("SKILL.md")
    playbook = _read("references/ENTITY_MAINTENANCE_PLAYBOOK.md")

    for doc in (skill, playbook):
        assert "Entities/<entity_id>.md" in doc
        assert "mentions" in doc
        assert "search" in doc
        assert "entity_expansion" in doc


def test_skill_teaches_self_anchor_and_proactive_relationship_updates() -> None:
    skill = _read("SKILL.md")

    assert "life-index entity --set-self --id ENTITY_ID --json" in skill
    assert "哪个实体是你本人" in skill
    assert "用户口述/纠正人物关系事实" in skill
    assert "主动复述并提议写入图谱" in skill


def test_api_documents_entity_profiles_stale_event() -> None:
    api = _read("docs/API.md")

    assert "`entity_profiles_stale`" in api
    assert "life-index abstract --entities" in api


def test_api_marks_retired_entity_primitives_as_removed_with_replacements() -> None:
    api = _read("docs/API.md")

    assert "Retired top-level primitives" in api
    assert "profile --id ENTITY_ID --json" in api
    assert "life-index abstract --entities --json" in api
    assert "`Entities/<entity_id>.md`" in api
    assert "candidate entities fail closed" in api.lower()
    assert "`--seed`" in api
    assert "`entity build --from-journals --preview --json`" in api
    assert "`--update`" in api
    assert "`entity --add-alias ALIAS --id ENTITY_ID`" in api
    assert "`--merge`" in api
    assert "`entity --review --action preview`" in api
    assert "`--delete`" in api
    assert "`entity maintain --delete --id ENTITY_ID --preview --json`" in api
