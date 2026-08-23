"""Public CLI contracts for recall-first retrieval truthfulness."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
_SANDBOX_MARKER = ".synthetic-d1-a-sandbox"
_DIAGNOSTIC_CONTEXT_LIMIT = 400


def _make_synthetic_data_dir(tmp_path: Path) -> Path:
    data_dir = tmp_path / "Life-Index"
    (data_dir / "Journals" / "2026" / "01").mkdir(parents=True)
    (data_dir / _SANDBOX_MARKER).write_text("synthetic only\n", encoding="utf-8")
    return data_dir


def _assert_synthetic_data_dir(data_dir: Path) -> None:
    """Fail closed before any behavior run can target configured user data."""
    resolved = data_dir.resolve()
    configured = os.environ.get("LIFE_INDEX_DATA_DIR")
    if configured and resolved == Path(configured).expanduser().resolve():
        raise AssertionError("refusing to run recall contract against configured data")
    default_data_dir = (Path.home() / "Documents" / "Life-Index").resolve()
    if resolved == default_data_dir:
        raise AssertionError("refusing to run recall contract against default user data")
    if not (resolved / _SANDBOX_MARKER).is_file():
        raise AssertionError("synthetic sandbox marker is missing")


def _write_journal(data_dir: Path, *, sequence: int, title: str, content: str) -> str:
    rel_path = f"Journals/2026/01/life-index_2026-01-01_{sequence:03d}.md"
    journal_path = data_dir / rel_path
    journal_path.write_text(
        "---\n"
        f"title: {title}\n"
        "date: 2026-01-01\n"
        "topic:\n"
        "  - synthetic\n"
        "tags: []\n"
        "people: []\n"
        "---\n\n"
        f"{content}\n",
        encoding="utf-8",
    )
    return rel_path


def _bounded_diagnostic_context(value: str) -> str:
    if len(value) <= _DIAGNOSTIC_CONTEXT_LIMIT:
        return value
    return f"{value[:_DIAGNOSTIC_CONTEXT_LIMIT]}...<truncated>"


def _run_search(data_dir: Path, query: str, *extra_args: str) -> dict:
    _assert_synthetic_data_dir(data_dir)
    env = {
        **os.environ,
        "LIFE_INDEX_DATA_DIR": str(data_dir),
        "LIFE_INDEX_NOISE_GATE": "1",
    }
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "tools.search_journals",
            "--query",
            query,
            "--no-index",
            *extra_args,
        ],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
        encoding="utf-8",
    )
    assert proc.returncode == 0, (
        "search failed: "
        f"stderr={_bounded_diagnostic_context(proc.stderr)!r}; "
        f"stdout={_bounded_diagnostic_context(proc.stdout)!r}"
    )
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise AssertionError(
            "search returned invalid JSON: "
            f"{exc}; stdout={_bounded_diagnostic_context(proc.stdout)!r}; "
            f"stderr={_bounded_diagnostic_context(proc.stderr)!r}"
        ) from exc


@pytest.mark.parametrize(
    ("query", "reason"),
    [
        pytest.param("菜谱推荐", "ood_topic", id="ood-topic"),
        pytest.param("不存在的合成记录", "negation_intent", id="negation-intent"),
        pytest.param("life indxxx", "typo_near_noise", id="typo-near-noise"),
    ],
)
def test_default_search_keeps_all_synthetic_token_matches_despite_noise_label(
    tmp_path: Path,
    query: str,
    reason: str,
) -> None:
    data_dir = _make_synthetic_data_dir(tmp_path)
    expected_path = _write_journal(
        data_dir,
        sequence=1,
        title=f"Synthetic {query} note",
        content=f"A neutral fixture containing the exact phrase {query} for retrieval.",
    )

    result = _run_search(data_dir, query)

    assert result["total_matches"] == 1
    returned_path = Path(result["merged_results"][0]["path"]).as_posix()
    assert returned_path.endswith(expected_path)
    assert f"query_classification: {reason}; retrieval_not_bypassed" in result["warnings"]


def test_public_blocker_executes_synthetic_core_assertion(tmp_path: Path) -> None:
    """Stable public-core target counted by the Tier 1 assertion sentinel."""
    data_dir = _make_synthetic_data_dir(tmp_path)
    expected_path = _write_journal(
        data_dir,
        sequence=1,
        title="Synthetic publiccoretoken note",
        content="A neutral fixture containing publiccoretoken.",
    )

    result = _run_search(data_dir, "publiccoretoken", "--limit", "0")

    assert result["total_matches"] == 1
    assert len(result["merged_results"]) == 1
    assert Path(result["merged_results"][0]["path"]).as_posix().endswith(expected_path)


def test_classifier_failure_is_advisory_and_does_not_suppress_token_match(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = _make_synthetic_data_dir(tmp_path)
    expected_path = _write_journal(
        data_dir,
        sequence=1,
        title="Synthetic classifierfailtoken note",
        content="A neutral fixture containing classifierfailtoken.",
    )
    _assert_synthetic_data_dir(data_dir)
    monkeypatch.setenv("LIFE_INDEX_DATA_DIR", str(data_dir))

    def raise_classifier_error(_query: str | None) -> tuple[bool, str | None]:
        raise RuntimeError("synthetic classifier failure")

    monkeypatch.setattr(
        "tools.search_journals.noise_gate.is_noise_query",
        raise_classifier_error,
    )

    from tools.search_journals.core import hierarchical_search

    result = hierarchical_search(
        query="classifierfailtoken",
        level=3,
        use_index=False,
        semantic=False,
    )

    assert result["total_matches"] == 1
    returned_path = Path(result["merged_results"][0]["path"]).as_posix()
    assert returned_path.endswith(expected_path)
    assert "query_classification_error: RuntimeError; retrieval_not_bypassed" in result["warnings"]


def test_invalid_json_diagnostic_bounds_stdout_and_stderr(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = _make_synthetic_data_dir(tmp_path)
    stdout_tail = "STDOUT_TAIL_SHOULD_NOT_APPEAR"
    stderr_tail = "STDERR_TAIL_SHOULD_NOT_APPEAR"
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout="not-json" + ("x" * 500) + stdout_tail,
            stderr=("e" * 500) + stderr_tail,
        ),
    )

    with pytest.raises(AssertionError) as exc_info:
        _run_search(data_dir, "synthetic")

    diagnostic = str(exc_info.value)
    assert "search returned invalid JSON" in diagnostic
    assert diagnostic.count("...<truncated>") == 2
    assert stdout_tail not in diagnostic
    assert stderr_tail not in diagnostic


def test_default_limit_only_changes_presentation_and_limit_zero_exposes_all_matches(
    tmp_path: Path,
) -> None:
    data_dir = _make_synthetic_data_dir(tmp_path)
    for sequence in range(1, 24):
        _write_journal(
            data_dir,
            sequence=sequence,
            title=f"Synthetic recalltoken note {sequence}",
            content=f"Neutral fixture {sequence} contains recalltoken.",
        )

    limited = _run_search(data_dir, "recalltoken")
    unlimited = _run_search(data_dir, "recalltoken", "--limit", "0")

    assert len(limited["merged_results"]) == 20
    assert len(unlimited["merged_results"]) == 23
    assert limited["total_matches"] == unlimited["total_matches"] == 23
    assert limited["has_more"] is True
    assert unlimited["has_more"] is False
    limited_paths = [item["path"] for item in limited["merged_results"]]
    unlimited_paths = [item["path"] for item in unlimited["merged_results"]]
    assert limited_paths == unlimited_paths[:20]
