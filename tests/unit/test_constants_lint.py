"""Phase 6-A: Search constants lint compliance test.

CHARTER 4.3 requires all numeric thresholds in search_journals/
to be managed constants in search_constants.py.
"""

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
LINT_SCRIPT = REPO_ROOT / "tools" / "eval" / "search_constants_lint.py"


def test_no_unmanaged_numeric_literals():
    """search_journals/ must not contain bare numeric thresholds (CHARTER 4.3)."""
    result = subprocess.run(
        [sys.executable, str(LINT_SCRIPT)],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        encoding="utf-8",
    )
    assert result.returncode == 0, f"Lint found violations:\n{result.stdout}\n{result.stderr}"


def test_removed_semantic_runtime_constants_are_not_exported():
    """Legacy semantic baseline/runtime constants should not survive the purge."""
    from tools.lib.search_constants import __all__

    assert "SEMANTIC_BASELINE_OFFSET" not in __all__
    assert "SEMANTIC_ABSOLUTE_FLOOR" not in __all__
    assert "SEMANTIC_SNIPPET_LENGTH" not in __all__


def test_total_exports_count():
    """Track total exported constants count (should not grow without review)."""
    from tools.lib.search_constants import __all__

    # Post Phase 6-A: 43 exports
    # Post Round 19 Phase 1-D C1-fuzzy: +4 fuzzy typo constants
    # Post R2-A2C: +1 reviewed location metadata ranking constant
    # Post gbrain Phase B: +1 reviewed source-tier ranking constant
    # Post WP-CLI-LEGACY-PURGE: -3 removed semantic runtime constants.
    # If this grows beyond 49, a new constant was added — review it.
    assert len(__all__) <= 49, (
        f"__all__ has {len(__all__)} exports (max 49). "
        "New constants must be reviewed for synonym merging."
    )
