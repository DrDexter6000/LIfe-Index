#!/usr/bin/env python3
"""Life Index aggregate core — deterministic counts, buckets, and claims.

Read-only, no LLM dependency. Reads journals from get_journals_dir(),
parses frontmatter, applies predicates, returns structured JSON.
"""

import re
import time
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from tools.lib.frontmatter import parse_frontmatter
from tools.lib.paths import get_journals_dir, get_user_data_dir
from tools.generate_index.navigation import (
    index_node_refs_for_range as _nav_index_node_refs_for_range,
    resolve_month_dir_from_ref as _nav_resolve_month_dir_from_ref,
)

VALID_UNITS = {"day", "week", "month", "entry"}
VALID_PREDICATES = {
    "journal_count",
    "entry_time_after",
    "term_presence",
    "entity_presence",
    "field_equals",
}

_SAFE_FIELD_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _parse_range(range_str: str) -> Tuple[date, date]:
    parts = range_str.split("..")
    if len(parts) != 2:
        raise ValueError(f"Invalid range format: {range_str!r}. Expected YYYY-MM-DD..YYYY-MM-DD.")
    since = date.fromisoformat(parts[0].strip())
    until = date.fromisoformat(parts[1].strip())
    if since > until:
        raise ValueError(f"Range start {since} is after end {until}.")
    return since, until


def _parse_predicate(predicate_str: str) -> Dict[str, Any]:
    if "=" in predicate_str:
        key, value = predicate_str.split("=", 1)
    else:
        key = predicate_str
        value = None

    if key not in VALID_PREDICATES:
        raise ValueError(f"Unknown predicate: {key!r}. Valid: {sorted(VALID_PREDICATES)}")

    result: Dict[str, Any] = {"type": key}

    if key == "entry_time_after":
        if value is None:
            raise ValueError("entry_time_after requires HH:MM value.")
        match = re.match(r"^(\d{1,2}):(\d{2})$", value.strip())
        if not match:
            raise ValueError(f"Invalid time format: {value!r}. Expected HH:MM.")
        hour, minute = int(match.group(1)), int(match.group(2))
        result["threshold"] = f"{hour:02d}:{minute:02d}"
        result["threshold_minutes"] = hour * 60 + minute
        result["definition"] = (
            f"journal timestamp later than "
            f"{result['threshold']}; "
            f"not proof of actual sleep time"
        )
    elif key == "term_presence":
        if value is None:
            raise ValueError("term_presence requires a TERM value.")
        result["term"] = value
        result["definition"] = (
            f"mention of '{value}' in journal content; "
            f"approximate recall-backed count, "
            f"not behavior proof"
        )
    elif key == "entity_presence":
        if value is None:
            raise ValueError("entity_presence requires an ENTITY_ID value.")
        result["entity_id"] = value
        result["definition"] = (
            f"presence of entity '{value}' " f"(primary name + aliases); recall-backed"
        )
    elif key == "journal_count":
        result["definition"] = "count of journal entries per aggregation unit"
    elif key == "field_equals":
        if value is None or ":" not in value:
            raise ValueError("field_equals requires FIELD:VALUE format.")
        field_part, value_part = value.split(":", 1)
        if not _SAFE_FIELD_RE.match(field_part):
            raise ValueError(
                f"Invalid field name: {field_part!r}. " f"Must match [A-Za-z_][A-Za-z0-9_]*."
            )
        result["field"] = field_part
        result["value"] = value_part
        result["definition"] = (
            f"frontmatter field '{field_part}' equals '{value_part}'; "
            f"deterministic frontmatter-data comparison"
        )

    return result


def _range_month_keys(since: date, until: date) -> set:
    keys: set = set()
    d = since
    while d <= until:
        keys.add(f"{d.year}-{d.month:02d}")
        if d.month == 12:
            d = date(d.year + 1, 1, 1)
        else:
            d = date(d.year, d.month + 1, 1)
    return keys


def _existing_month_dirs_in_range(journals_dir: Path, since: date, until: date) -> set:
    """Cheap month-directory census: which YYYY-MM dirs exist inside the range.

    Read-only on directory NAMES only; never touches journal file contents.
    """
    existing: set = set()
    if not journals_dir.is_dir():
        return existing
    range_keys = _range_month_keys(since, until)
    for child in journals_dir.iterdir():
        if not child.is_dir() or not re.fullmatch(r"\d{4}", child.name):
            continue
        for sub in child.iterdir():
            if not sub.is_dir() or not re.fullmatch(r"\d{2}", sub.name):
                continue
            key = f"{child.name}-{sub.name}"
            if key in range_keys:
                existing.add(key)
    return existing


def _new_scan_stats(mode: str) -> Dict[str, Any]:
    return {
        "mode": mode,
        "visited_months": set(),
        "existing_range_months": set(),
        "months_consistent": True,
        "candidate_count": 0,
        "unparseable_count": 0,
    }


def _scan_journals(
    journals_dir: Path, since: date, until: date
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Enumerate candidate journals and record the enumeration facts verbatim.

    Returns ``(entries, scan_stats)``. ``scan_stats`` carries this run's own
    enumeration facts for the ``retrieval_coverage.v1`` projection:

    * ``mode``: ``"fallback_full_scan"`` (whole-tree rglob) or ``"month_refs"``
      (per-month glob over navigation refs);
    * ``visited_months``: months whose directories were actually globbed;
    * ``existing_range_months``: month directories present on disk within range;
    * ``candidate_count``: candidate paths observed (parsed + unparseable;
      excludes ``.revisions`` policy skips and out-of-range files);
    * ``unparseable_count``: candidates that failed to parse.
    """
    entries: List[Dict[str, Any]] = []
    stats = _new_scan_stats("month_refs")
    if not journals_dir.exists():
        return entries, stats

    def _consume(md_file: Path) -> None:
        entry, outcome = _parse_journal_file(md_file, since, until, journals_dir)
        if outcome == "policy_skip":
            return
        stats["candidate_count"] += 1
        if outcome == "unparseable":
            stats["unparseable_count"] += 1
        elif entry is not None:
            entries.append(entry)

    month_refs = _nav_index_node_refs_for_range(since.isoformat(), until.isoformat())
    if not month_refs:
        stats["mode"] = "fallback_full_scan"
        for md_file in sorted(journals_dir.rglob("life-index_*.md")):
            _consume(md_file)
        return entries, stats

    for ref in month_refs:
        month_dir = _nav_resolve_month_dir_from_ref(journals_dir, ref)
        if month_dir is None:
            continue
        if not month_dir.is_dir():
            continue
        rel_parts = month_dir.relative_to(journals_dir).parts
        if len(rel_parts) == 2:
            stats["visited_months"].add(f"{rel_parts[0]}-{rel_parts[1]}")
        for md_file in sorted(month_dir.glob("life-index_*.md")):
            _consume(md_file)

    stats["existing_range_months"] = _existing_month_dirs_in_range(journals_dir, since, until)
    stats["months_consistent"] = stats["visited_months"] == stats["existing_range_months"]

    return entries, stats


def _parse_journal_file(
    md_file: Path, since: date, until: date, journals_dir: Path
) -> Tuple[Optional[Dict[str, Any]], str]:
    """Parse one journal file into ``(entry, outcome)`` without behavior change.

    ``outcome`` classifies why an entry was or was not produced, so coverage can
    separate genuine parse failures from established policy skips and scope
    filtering: ``"parsed"`` | ``"out_of_range"`` | ``"unparseable"`` |
    ``"policy_skip"``.
    """
    rel_parts = md_file.parts
    if any(part == ".revisions" for part in rel_parts):
        return None, "policy_skip"

    try:
        content = md_file.read_text(encoding="utf-8")
    except (IOError, OSError):
        return None, "unparseable"

    metadata, body = parse_frontmatter(content)

    date_val = metadata.get("date", "")
    entry_date: Optional[date] = None
    entry_time: Optional[str] = None

    if isinstance(date_val, str) and date_val:
        iso_match = re.match(r"^(\d{4}-\d{2}-\d{2})(?:[T ](\d{2}:\d{2}(?::\d{2})?))?", date_val)
        if iso_match:
            try:
                entry_date = date.fromisoformat(iso_match.group(1))
                if iso_match.group(2):
                    entry_time = iso_match.group(2)
            except ValueError:
                return None, "unparseable"
        else:
            return None, "unparseable"

    if entry_time is None:
        time_val = metadata.get("time", "")
        if isinstance(time_val, str) and time_val:
            time_match = re.match(r"^(\d{1,2}:\d{2}(?::\d{2})?)$", time_val.strip())
            if time_match:
                entry_time = time_match.group(1)
        elif isinstance(time_val, int):
            if time_val <= 1439:
                entry_time = f"{time_val // 60:02d}:{time_val % 60:02d}"
            else:
                h = time_val // 3600
                rem = time_val % 3600
                m = rem // 60
                s = rem % 60
                if s > 0:
                    entry_time = f"{h:02d}:{m:02d}:{s:02d}"
                else:
                    entry_time = f"{h:02d}:{m:02d}"

    if entry_date is None:
        stem = md_file.stem
        stem_match = re.search(r"(\d{4}-\d{2}-\d{2})", stem)
        if stem_match:
            try:
                entry_date = date.fromisoformat(stem_match.group(1))
            except ValueError:
                return None, "unparseable"
        else:
            return None, "unparseable"

    if entry_date < since or entry_date > until:
        return None, "out_of_range"

    try:
        data_dir = get_user_data_dir()
        rel_path = md_file.relative_to(data_dir).as_posix()
    except ValueError:
        rel_path = md_file.as_posix()

    return (
        {
            "path": rel_path,
            "date": entry_date,
            "time": entry_time,
            "body": body,
            "metadata": metadata,
        },
        "parsed",
    )


def _bucket_key(entry_date: date, unit: str) -> str:
    if unit == "day":
        return entry_date.isoformat()
    elif unit == "week":
        iso = entry_date.isocalendar()
        return f"{iso[0]}-W{iso[1]:02d}"
    elif unit == "month":
        return f"{entry_date.year}-{entry_date.month:02d}"
    return entry_date.isoformat()


def _compute_metric(predicate: Dict[str, Any]) -> str:
    ptype = predicate["type"]
    if ptype == "journal_count":
        return "journal_count"
    elif ptype == "entry_time_after":
        return "entry_count"
    elif ptype == "term_presence":
        return "term_presence_count"
    elif ptype == "entity_presence":
        return "entity_presence_count"
    elif ptype == "field_equals":
        return "field_equals_count"
    return "entry_count"


def _apply_field_equals(
    entries: List[Dict[str, Any]], pred: Dict[str, Any]
) -> Tuple[List[Any], List[Any]]:
    target_field = pred["field"]
    target_value = pred["value"].casefold()
    matched: List[Any] = []
    excluded: List[Any] = []

    for entry in entries:
        field_val = entry.get("metadata", {}).get(target_field)
        if isinstance(field_val, list):
            is_match = any(str(item).casefold() == target_value for item in field_val)
        else:
            is_match = field_val is not None and str(field_val).casefold() == target_value
        (matched if is_match else excluded).append(entry["path"])

    return matched, excluded


def _build_partial_bounds(
    *,
    unit: str,
    entries: List[Dict[str, Any]],
    matched: List[Any],
    unknown: List[Any],
    count: int,
) -> Dict[str, Any]:
    unknown_count = len(unknown)
    if unit == "entry":
        min_count = len(matched)
        max_count = len(matched) + unknown_count
        unknown_bucket_count = unknown_count
    else:
        matched_paths = set(matched)
        unknown_paths = {u["path"] for u in unknown}
        matched_bucket_keys: set = set()
        unknown_bucket_keys: set = set()
        for entry in entries:
            entry_path = entry["path"]
            if entry_path in matched_paths:
                matched_bucket_keys.add(_bucket_key(entry["date"], unit))
            if entry_path in unknown_paths:
                unknown_bucket_keys.add(_bucket_key(entry["date"], unit))
        min_count = count
        max_count = count + len(unknown_bucket_keys - matched_bucket_keys)
        unknown_bucket_count = len(unknown_bucket_keys)

    return {
        "min_count": min_count,
        "max_count": max_count,
        "unknown_count": unknown_count,
        "unknown_bucket_count": unknown_bucket_count,
        "count_semantics": "partial_lower_bound",
    }


def run_aggregate(
    range_str: str,
    unit: str,
    predicate: str,
    query: str = "",
    explain: bool = False,
) -> Dict[str, Any]:
    t0 = time.perf_counter()

    error_result_base: Dict[str, Any] = {
        "query": query,
        "command": "aggregate",
        "metric": "",
        "unit": unit,
        "range": {},
        "predicate": {},
        "result": {},
        "buckets": [],
        "matched_entries": [],
        "excluded_entries": [],
        "unknown_entries": [],
        "evidence_paths": [],
        "limitations": [],
        "performance": {},
    }

    if unit not in VALID_UNITS:
        return {
            **error_result_base,
            "success": False,
            "error": {
                "code": "E0001",
                "message": (f"Invalid unit: {unit!r}. " f"Valid: {sorted(VALID_UNITS)}"),
            },
        }

    try:
        since, until = _parse_range(range_str)
    except ValueError as e:
        return {
            **error_result_base,
            "success": False,
            "error": {"code": "E0001", "message": str(e)},
        }

    try:
        pred = _parse_predicate(predicate)
    except ValueError as e:
        return {
            **error_result_base,
            "success": False,
            "error": {"code": "E0001", "message": str(e)},
        }

    journals_dir = get_journals_dir()
    entries, scan_stats = _scan_journals(journals_dir, since, until)

    metric = _compute_metric(pred)
    pred_type = pred["type"]

    matched: List[Any] = []
    excluded: List[Any] = []
    unknown: List[Any] = []

    if pred_type == "journal_count":
        matched = [entry["path"] for entry in entries]
        exactness = "exact"
        confidence = "high"
        limitations: List[str] = []

    elif pred_type == "entry_time_after":
        threshold_min = pred["threshold_minutes"]
        has_unknown = False
        for entry in entries:
            if entry["time"] is not None:
                time_parts = entry["time"].split(":")
                entry_min = int(time_parts[0]) * 60 + int(time_parts[1])
                if entry_min >= threshold_min:
                    matched.append(entry["path"])
                else:
                    excluded.append(entry["path"])
            else:
                has_unknown = True
                unknown.append(
                    {
                        "path": entry["path"],
                        "reason": "no_time_field_available",
                    }
                )

        if has_unknown:
            exactness = "partial"
            confidence = "high"
            limitations = [
                "No reliable time-of-day field was available " "for one or more journal entries."
            ]
        else:
            exactness = "exact"
            confidence = "high"
            limitations = ["Late journal write time is not proof of actual sleep time."]

    elif pred_type == "term_presence":
        term = pred["term"]
        for entry in entries:
            searchable = (
                (entry.get("body") or "")
                + " "
                + " ".join(str(v) for v in entry.get("metadata", {}).values() if isinstance(v, str))
            )
            if term.casefold() in searchable.casefold():
                matched.append(entry["path"])
            else:
                excluded.append(entry["path"])
        exactness = "approximate"
        confidence = "medium"
        limitations = [
            "Term mention count is recall-backed, " "not proof of the real-world behavior.",
            "False positives and false negatives " "are possible depending on retrieval quality.",
        ]

    elif pred_type == "entity_presence":
        entity_id = pred["entity_id"]
        data_dir = get_user_data_dir()
        graph_path = data_dir / "entity_graph.yaml"
        search_terms = [entity_id]

        try:
            from tools.lib.entity_graph import load_entity_graph

            entities = load_entity_graph(graph_path)
            for ent in entities:
                if ent.get("id", "").lower() == entity_id.lower():
                    search_terms.append(ent.get("primary_name", ""))
                    for alias in ent.get("aliases", []):
                        search_terms.append(alias)
                    break
        except Exception:
            pass

        for entry in entries:
            searchable = (
                (entry.get("body") or "")
                + " "
                + " ".join(str(v) for v in entry.get("metadata", {}).values() if isinstance(v, str))
            )
            found = any(t.casefold() in searchable.casefold() for t in search_terms if t)
            if found:
                matched.append(entry["path"])
            else:
                excluded.append(entry["path"])
        exactness = "approximate"
        confidence = "medium"
        limitations = [
            "Entity presence is recall-backed, not deterministic proof.",
            "Alias expansion depends on entity_graph.yaml completeness.",
        ]
    elif pred_type == "field_equals":
        matched, excluded = _apply_field_equals(entries, pred)
        exactness = "exact"
        confidence = "high"
        limitations = ["Comparison limited to frontmatter data fields."]
    else:
        return {
            **error_result_base,
            "success": False,
            "error": {
                "code": "E0001",
                "message": (f"Unhandled predicate type: {pred_type}"),
            },
        }

    if unit == "entry":
        count = len(matched)
        buckets: List[Dict[str, Any]] = []
    else:
        day_to_entries: Dict[str, List[str]] = defaultdict(list)
        for entry in entries:
            e_path = entry["path"]
            key = _bucket_key(entry["date"], unit)
            day_to_entries[key].append(e_path)

        matched_set = set(matched)
        buckets = []
        count = 0
        for key in sorted(day_to_entries.keys()):
            bucket_paths = day_to_entries[key]
            bucket_matched = [p for p in bucket_paths if p in matched_set]
            if bucket_matched:
                count += 1
            buckets.append(
                {
                    "key": key,
                    "count": len(bucket_matched),
                    "total": len(bucket_paths),
                    "evidence_paths": [p for p in bucket_paths],
                }
            )

    partial_bounds: Dict[str, Any] = {}
    if exactness == "partial" and pred_type == "entry_time_after":
        partial_bounds = _build_partial_bounds(
            unit=unit,
            entries=entries,
            matched=matched,
            unknown=unknown,
            count=count,
        )

    denominator = 0
    if entries:
        total_days = (until - since).days + 1
        if unit == "day":
            denominator = total_days
        elif unit == "week":
            denominator = (total_days + 6) // 7
        elif unit == "month":
            months = set()
            d = since
            while d <= until:
                months.add(f"{d.year}-{d.month:02d}")
                if d.month == 12:
                    d = date(d.year + 1, 1, 1)
                else:
                    d = date(d.year, d.month + 1, 1)
            denominator = len(months)
        elif unit == "entry":
            denominator = len(entries)

    evidence_paths = sorted(set(matched + excluded + [u["path"] for u in unknown]))

    if explain and pred.get("definition"):
        limitations = [pred["definition"]] + limitations

    # Parse-failure candidates are disclosed through the existing limitations
    # channel; no new closed-set partial reason is introduced for them.
    unparseable_count = int(scan_stats.get("unparseable_count", 0))
    if unparseable_count > 0:
        limitations.append(
            f"{unparseable_count} journal file(s) failed to parse and were "
            "excluded from this aggregation."
        )

    entry_dates: Dict[str, str] = {}
    bucket_by_path: Dict[str, str] = {}
    for entry in entries:
        e_path = entry["path"]
        entry_dates[e_path] = entry["date"].isoformat()
        bucket_by_path[e_path] = _bucket_key(entry["date"], unit)

    elapsed_ms = (time.perf_counter() - t0) * 1000

    result: Dict[str, Any] = {
        "success": True,
        "query": query,
        "command": "aggregate",
        "metric": metric,
        "unit": unit,
        "range": {"since": since.isoformat(), "until": until.isoformat()},
        "predicate": {
            "type": pred["type"],
            **({"threshold": pred["threshold"]} if "threshold" in pred else {}),
            **({"term": pred["term"]} if "term" in pred else {}),
            **({"entity_id": pred["entity_id"]} if "entity_id" in pred else {}),
            **({"field": pred["field"]} if "field" in pred else {}),
            **({"value": pred["value"]} if "value" in pred else {}),
            "definition": pred.get("definition", ""),
        },
        "result": {
            "count": count,
            "denominator": denominator,
            "exactness": exactness,
            "confidence": confidence,
            **partial_bounds,
        },
        "buckets": buckets,
        "matched_entries": sorted(matched),
        "excluded_entries": sorted(excluded),
        "unknown_entries": unknown,
        "evidence_paths": evidence_paths,
        "limitations": limitations,
        "performance": {"total_time_ms": round(elapsed_ms, 1)},
    }

    from .claim_envelope import (
        build_claim_envelope,
        build_evidence_pack,
        build_retrieval_coverage_from_scan,
    )

    result["claim_envelope"] = build_claim_envelope(result)
    result["evidence_pack"] = build_evidence_pack(
        aggregate_result=result,
        entry_dates=entry_dates,
        bucket_by_path=bucket_by_path,
        retrieval_coverage=build_retrieval_coverage_from_scan(
            scan_stats, returned=len(entry_dates)
        ),
    )

    return result
