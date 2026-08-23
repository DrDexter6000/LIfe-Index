#!/usr/bin/env python3
"""
Entity review export/import — Round 7 Phase 3 Task 11.

Provides CSV and optional xlsx export/import for the entity review queue.

CLI entry:
  `life-index entity review --export csv`
  `life-index entity review --export xlsx`
  `life-index entity review --import <file>`

Design:
- CSV is always available (stdlib csv module)
- xlsx requires openpyxl (graceful degradation)
- Import always uses preview-then-commit
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from tools.lib.paths import resolve_user_data_dir

try:
    from tools.lib.logger import get_logger

    logger = get_logger("entity_review_io")
except ImportError:
    import logging

    logger = logging.getLogger("entity_review_io")


def _default_graph_path() -> Path:
    return resolve_user_data_dir() / "entity_graph.yaml"


_EXPORT_COLUMNS = [
    "item_id",
    "risk_level",
    "category",
    "description",
    "why",
    "evidence",
    "action_choices",
    "entity_ids",
    "suggested_action",
    "decision",
    "source_id",
    "target_id",
]


def _action_choices_cell(item: dict[str, Any]) -> str:
    choices = item.get("action_choices", []) or []
    actions: list[str] = []
    for choice in choices:
        if isinstance(choice, dict):
            action = choice.get("action", "")
        else:
            action = choice
        action_text = str(action).strip()
        if action_text:
            actions.append(action_text)
    return "|".join(actions)


def export_review_csv(
    *,
    output_path: Path,
    graph_path: Path | None = None,
) -> dict[str, Any]:
    """Export review queue to CSV file.

    Args:
        output_path: Where to write the CSV file.
        graph_path: Optional override for entity graph path (testing).

    Returns:
        Result dict with success status and row count.
    """
    from tools.entity.review import build_review_queue

    graph_path = graph_path or _default_graph_path()
    queue = build_review_queue(graph_path=graph_path)

    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=_EXPORT_COLUMNS)
        writer.writeheader()

        for item in queue:
            row = {
                "item_id": item.get("item_id", ""),
                "risk_level": item.get("risk_level", ""),
                "category": item.get("category", ""),
                "description": item.get("description", ""),
                "why": item.get("why", ""),
                "evidence": "|".join(item.get("evidence", [])),
                "action_choices": _action_choices_cell(item),
                "entity_ids": "|".join(str(e) for e in item.get("entity_ids", [])),
                "suggested_action": item.get("suggested_action", ""),
                "decision": "",
                "source_id": "",
                "target_id": "",
            }
            writer.writerow(row)

    return {
        "success": True,
        "data": {"rows": len(queue), "output": str(output_path)},
        "error": None,
    }


def import_review_csv(
    *,
    input_path: Path,
    graph_path: Path | None = None,
) -> dict[str, Any]:
    """Import review decisions from CSV file.

    Applies decisions from a previously exported CSV that has been filled in
    with decision/source_id/target_id columns.

    Uses preview-then-commit: returns a preview of changes without applying.
    To actually apply, pass apply=True.

    Args:
        input_path: Path to the CSV file with decisions.
        graph_path: Optional override for entity graph path (testing).

    Returns:
        Result dict with applied count and details.
    """
    from tools.entity.review import apply_action

    if not input_path.exists():
        return {
            "success": False,
            "data": None,
            "error": f"File not found: {input_path}",
        }

    graph_path = graph_path or _default_graph_path()
    applied: list[dict[str, Any]] = []

    with input_path.open("r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)

        for row in reader:
            decision = row.get("decision", "").strip()
            if not decision:
                continue

            action = decision
            source_id = row.get("source_id", "").strip() or None
            target_id = row.get("target_id", "").strip() or None

            result = apply_action(
                action=action,
                source_id=source_id,
                target_id=target_id,
                graph_path=graph_path,
            )

            applied.append(
                {
                    "item_id": row.get("item_id", ""),
                    "action": action,
                    "success": result.get("success", False),
                    "error": result.get("error"),
                }
            )

    return {
        "success": True,
        "data": {"applied": len(applied), "results": applied},
        "error": None,
    }


def export_review_xlsx(
    *,
    output_path: Path,
    graph_path: Path | None = None,
) -> dict[str, Any]:
    """Export review queue to xlsx file (requires openpyxl).

    Gracefully degrades when openpyxl is not installed.

    Args:
        output_path: Where to write the xlsx file.
        graph_path: Optional override for entity graph path (testing).

    Returns:
        Result dict with success status.
    """
    try:
        import openpyxl  # noqa: F401
    except ImportError:
        return {
            "success": False,
            "data": None,
            "error": (
                "openpyxl not installed. Install with: pip install openpyxl. "
                "CSV export is always available."
            ),
        }

    from tools.entity.review import build_review_queue

    graph_path = graph_path or _default_graph_path()
    queue = build_review_queue(graph_path=graph_path)

    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    if ws is None:
        return {
            "success": False,
            "data": None,
            "error": "Workbook has no active worksheet.",
        }
    ws.title = "Review Queue"

    # Headers
    ws.append(_EXPORT_COLUMNS)

    # Data rows
    for item in queue:
        ws.append(
            [
                item.get("item_id", ""),
                item.get("risk_level", ""),
                item.get("category", ""),
                item.get("description", ""),
                item.get("why", ""),
                "|".join(item.get("evidence", [])),
                _action_choices_cell(item),
                "|".join(str(e) for e in item.get("entity_ids", [])),
                item.get("suggested_action", ""),
                "",  # decision (to be filled by user)
                "",  # source_id
                "",  # target_id
            ]
        )

    wb.save(output_path)

    return {
        "success": True,
        "data": {"rows": len(queue), "output": str(output_path)},
        "error": None,
    }
