#!/usr/bin/env python3
"""TDD tests for supplement mode public-contract guard.

These tests prove that the supplement mode remains private and is not exposed
through public CLI/default search behavior. They are test-only protection — no
source code changes should be needed for these to pass.

Contract:
  1. ``--semantic-policy supplement`` is rejected by argparse before search runs.
  2. ``hierarchical_search`` ``semantic_policy`` annotation admits only
     ``hybrid`` and ``fallback``.
  3. ``tools.search_journals.supplement_policy`` does not export public default
     names such as ``SEMANTIC_POLICY`` or ``MAX_RESULTS``.

Tests must not require real user data or semantic model downloads.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import get_args, get_type_hints

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

# ---------------------------------------------------------------------------
# 1. CLI rejects --semantic-policy supplement
# ---------------------------------------------------------------------------


class TestCLISupplementPolicyRejected:
    """``--semantic-policy supplement`` must be rejected by argparse before
    the search pipeline is entered."""

    def test_supplement_rejected_by_argparse(self):
        """Running with --semantic-policy supplement must exit with code 2
        (argparse error) rather than executing search."""
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "tools.search_journals",
                "--query",
                "x",
                "--semantic-policy",
                "supplement",
            ],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
            encoding="utf-8",
        )
        assert result.returncode == 2, (
            f"Expected exit code 2 (argparse rejection), got {result.returncode}. "
            f"stderr: {result.stderr!r}"
        )

    def test_supplement_does_not_produce_search_output(self):
        """Argparse rejection must not produce JSON search output on stdout."""
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "tools.search_journals",
                "--query",
                "x",
                "--semantic-policy",
                "supplement",
            ],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
            encoding="utf-8",
        )
        # If stdout is non-empty it should not be valid JSON search output
        if result.stdout.strip():
            import json

            with pytest.raises(json.JSONDecodeError):
                json.loads(result.stdout)


# ---------------------------------------------------------------------------
# 2. hierarchical_search semantic_policy annotation admits only hybrid/fallback
# ---------------------------------------------------------------------------


class TestHierarchicalSearchPolicyAnnotation:
    """The ``semantic_policy`` parameter type annotation must only allow
    ``hybrid`` and ``fallback`` — not ``supplement``."""

    def test_annotation_is_literal_with_two_values(self):
        from tools.search_journals.core import hierarchical_search

        hints = get_type_hints(hierarchical_search)
        annotation = hints["semantic_policy"]
        allowed = get_args(annotation)
        assert set(allowed) == {"hybrid", "fallback"}, (
            f"semantic_policy Literal must be {{'hybrid', 'fallback'}}, " f"got {set(allowed)}"
        )

    def test_supplement_not_in_annotation(self):
        from tools.search_journals.core import hierarchical_search

        hints = get_type_hints(hierarchical_search)
        allowed = get_args(hints["semantic_policy"])
        assert (
            "supplement" not in allowed
        ), "'supplement' must not appear in semantic_policy Literal annotation"


# ---------------------------------------------------------------------------
# 3. supplement_policy does not export public default names
# ---------------------------------------------------------------------------


class TestSupplementPolicyNoPublicDefaults:
    """``tools.search_journals.supplement_policy`` must not export public
    default names such as ``SEMANTIC_POLICY`` or ``MAX_RESULTS``."""

    def test_no_semantic_policy_export(self):
        import tools.search_journals.supplement_policy as sp

        assert not hasattr(
            sp, "SEMANTIC_POLICY"
        ), "supplement_policy must not export SEMANTIC_POLICY"

    def test_no_max_results_export(self):
        import tools.search_journals.supplement_policy as sp

        assert not hasattr(sp, "MAX_RESULTS"), "supplement_policy must not export MAX_RESULTS"

    def test_no_public_all_export(self):
        """``__all__`` must not contain supplement-mode constants."""
        import tools.search_journals.supplement_policy as sp

        if hasattr(sp, "__all__"):
            public_names = set(sp.__all__)
        else:
            # No __all__ means every non-underscore name is public
            public_names = {
                name for name in dir(sp) if not name.startswith("_") and not name.startswith("__")
            }

        forbidden = {"SEMANTIC_POLICY", "MAX_RESULTS", "SUPPLEMENT_MODE"}
        leaked = public_names & forbidden
        assert not leaked, f"supplement_policy exports forbidden names: {leaked}"

    def test_only_private_helpers_exported(self):
        """Module should only export underscore-prefixed helpers.

        ``from __future__ import annotations`` and ``from typing import ...``
        leak into ``dir()`` as public names; we filter those out so the test
        targets business-logic exports only.
        """
        import typing

        import tools.search_journals.supplement_policy as sp

        typing_names = set(dir(typing))

        if hasattr(sp, "__all__"):
            public_names = {n for n in sp.__all__ if not n.startswith("_")}
        else:
            public_names = {
                name
                for name in dir(sp)
                if not name.startswith("_")
                and not name.startswith("__")
                and name not in typing_names
                and name != "annotations"
            }

        assert (
            not public_names
        ), f"supplement_policy should have no public exports, found: {public_names}"
