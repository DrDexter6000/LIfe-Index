#!/usr/bin/env python3
"""Deterministic materialized Index B navigation documents."""

from __future__ import annotations

import re
import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from tools.generate_index.builder import safe_relative_path
from tools.lib.facet_canonicalization import FacetCanonicalizer, load_facet_canonicalizer
from tools.lib.frontmatter import parse_frontmatter
from tools.lib.paths import get_journals_dir, get_user_data_dir

INDEX_B_SCHEMA_VERSION = "m31.index_tree.index_b.v0"
INDEX_B_MANIFEST_SCHEMA_VERSION = "m31.index_tree.index_b.manifest.v0"
INDEX_B_DIR = ".life-index/index-b"
INDEX_B_MANIFEST = "manifest.json"
_MONTH_RE = re.compile(r"^\d{4}-\d{2}$")
_JOURNAL_DATE_RE = re.compile(r"life-index_(\d{4}-\d{2}-\d{2})_\d{3}\.md$")


@dataclass(frozen=True)
class FacetSpec:
    name: str
    fields: tuple[str, ...]


@dataclass(frozen=True)
class IndexBEntry:
    rel_path: str
    year: str
    month: str
    date: str
    title: str
    metadata: dict[str, Any]


@dataclass(frozen=True)
class IndexBDocSpec:
    key: str
    path: Path
    rel_path: str
    text: str
    entries: tuple[IndexBEntry, ...]


FACETS: tuple[FacetSpec, ...] = (
    FacetSpec("weather", ("weather",)),
    FacetSpec("location", ("location",)),
    FacetSpec("topic", ("topic", "topics")),
    FacetSpec("project", ("project", "projects")),
    FacetSpec("tag", ("tags", "tag")),
    FacetSpec("people", ("people",)),
)


def _generated_at() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_month(value: str | None, *, fallback: str | None = None) -> str | None:
    if value is None or not value.strip():
        return fallback
    text = value.strip()
    if not _MONTH_RE.match(text):
        raise ValueError(f"month must use YYYY-MM format, got: {value!r}")
    return text


def _entry_in_range(entry: IndexBEntry, date_from: str | None, date_to: str | None) -> bool:
    entry_month = f"{entry.year}-{entry.month}"
    if date_from is not None and entry_month < date_from:
        return False
    if date_to is not None and entry_month > date_to:
        return False
    return True


def _parse_frontmatter(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return {}
    if not text.startswith("---\n"):
        return {}
    try:
        metadata, _body = parse_frontmatter(text)
    except (TypeError, ValueError):
        return {}
    return metadata if isinstance(metadata, dict) else {}


def _date_from_filename(path: Path) -> str:
    match = _JOURNAL_DATE_RE.match(path.name)
    return match.group(1) if match else ""


def _iter_values(value: Any) -> Iterable[str]:
    if isinstance(value, list):
        for item in value:
            text = str(item).strip()
            if text:
                yield text
        return
    text = str(value or "").strip()
    if text:
        yield text


def _raw_facet_values(entry: IndexBEntry, spec: FacetSpec) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    for field in spec.fields:
        for value in _iter_values(entry.metadata.get(field)):
            if value not in seen:
                seen.add(value)
                values.append(value)
    return values


def _facet_values(
    entry: IndexBEntry, spec: FacetSpec, canonicalizer: FacetCanonicalizer | None = None
) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    for raw_value in _raw_facet_values(entry, spec):
        value = (
            canonicalizer.canonicalize(spec.name, raw_value).value
            if canonicalizer is not None
            else raw_value
        )
        if value and value not in seen:
            seen.add(value)
            values.append(value)
    return values


def _collect_entries_with_scan(
    date_from: str | None, date_to: str | None
) -> tuple[list[IndexBEntry], dict[str, Any]]:
    """Collect scoped entries plus this scan's own enumeration facts.

    The returned ``entries`` list is identical to :func:`_collect_entries`; the
    second element reports the collection facts that the ``exhaustive`` flag and
    the unified ``retrieval_coverage.v1`` object are projected from:

    * ``scanned``: the directory walk ran to completion;
    * ``skipped``: one record per candidate silently skipped by the guards
      (``not_a_regular_file`` / ``relative_path_unresolvable`` /
      ``unexpected_path_depth``).
    """
    data_dir = get_user_data_dir()
    journals_dir = get_journals_dir()
    entries: list[IndexBEntry] = []
    skipped: list[dict[str, str]] = []
    for path in sorted(journals_dir.glob("*/*/life-index_*.md")):
        if not path.is_file():
            skipped.append(_skip_record(path, journals_dir, "not_a_regular_file"))
            continue
        rel = safe_relative_path(path, data_dir)
        if not rel:
            skipped.append(_skip_record(path, journals_dir, "relative_path_unresolvable"))
            continue
        parts = path.relative_to(journals_dir).parts
        if len(parts) < 3:
            skipped.append(_skip_record(path, journals_dir, "unexpected_path_depth"))
            continue
        year, month = parts[0], parts[1]
        metadata = _parse_frontmatter(path)
        date_value = str(metadata.get("date") or _date_from_filename(path))
        entry = IndexBEntry(
            rel_path=rel,
            year=year,
            month=month,
            date=date_value,
            title=str(metadata.get("title") or path.stem),
            metadata=metadata,
        )
        if _entry_in_range(entry, date_from, date_to):
            entries.append(entry)
    return entries, {"scanned": True, "skipped": skipped}


def _skip_record(path: Path, journals_dir: Path, reason: str) -> dict[str, str]:
    try:
        rel = path.relative_to(journals_dir).as_posix()
    except ValueError:
        rel = path.name
    return {"path": rel, "reason": reason}


def _collect_entries(date_from: str | None, date_to: str | None) -> list[IndexBEntry]:
    entries, _scan_facts = _collect_entries_with_scan(date_from, date_to)
    return entries


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(65536), b""):
                digest.update(chunk)
    except OSError:
        return "missing"
    return digest.hexdigest()


def _source_hash(data_dir: Path, entries: Iterable[IndexBEntry]) -> str:
    digest = hashlib.sha256()
    for entry in sorted(entries, key=lambda item: item.rel_path):
        path = data_dir / entry.rel_path
        digest.update(entry.rel_path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(_sha256_file(path).encode("ascii"))
        digest.update(b"\0")
    return digest.hexdigest()


def _escape_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ").strip()


def _doc_rel(*parts: str) -> str:
    return "/".join((INDEX_B_DIR, *parts))


def _frontmatter(scope: str, date_from: str | None, date_to: str | None, count: int) -> str:
    lines = [
        "---",
        f"schema_version: {INDEX_B_SCHEMA_VERSION}",
        "generator: life-index index-tree materialize",
        f"scope: {scope}",
        f"entry_count: {count}",
    ]
    if date_from:
        lines.append(f"date_from: {date_from}")
    if date_to:
        lines.append(f"date_to: {date_to}")
    lines.extend(["---", ""])
    return "\n".join(lines)


def _facet_markdown(entries: list[IndexBEntry], canonicalizer: FacetCanonicalizer) -> str:
    lines = ["## Facets", ""]
    for spec in FACETS:
        buckets: dict[str, list[str]] = defaultdict(list)
        for entry in entries:
            for value in _facet_values(entry, spec, canonicalizer):
                buckets[value].append(entry.rel_path)
        lines.extend([f"### {spec.name}", "", "| value | count | pointers |", "|---|---:|---|"])
        if not buckets:
            lines.append("| (none) | 0 | |")
        else:
            counts = Counter({value: len(paths) for value, paths in buckets.items()})
            for value, count in sorted(counts.items(), key=lambda item: (-item[1], item[0])):
                pointers = ", ".join(sorted(buckets[value]))
                lines.append(f"| {_escape_cell(value)} | {count} | {_escape_cell(pointers)} |")
        lines.append("")
    return "\n".join(lines)


def _entry_pointer_markdown(entries: list[IndexBEntry]) -> str:
    lines = ["## Entry Pointers", "", "| date | title | path |", "|---|---|---|"]
    if not entries:
        lines.append("| (none) | | |")
    for entry in entries:
        lines.append(
            f"| {_escape_cell(entry.date)} | {_escape_cell(entry.title)} | "
            f"{_escape_cell(entry.rel_path)} |"
        )
    lines.append("")
    return "\n".join(lines)


def _root_doc(
    entries: list[IndexBEntry],
    years: dict[str, list[IndexBEntry]],
    date_from: str | None,
    date_to: str | None,
    canonicalizer: FacetCanonicalizer,
) -> str:
    lines = [
        _frontmatter("root", date_from, date_to, len(entries)),
        "# Index B Root Navigation",
        "",
        "Deterministic, rebuildable facet navigation. It is not a summary and does not "
        "replace journal evidence.",
        "",
        "## Child Nodes",
        "",
        "| year | count | doc |",
        "|---|---:|---|",
    ]
    for year, year_entries in sorted(years.items()):
        lines.append(f"| {year} | {len(year_entries)} | {_doc_rel('Journals', year, 'index.md')} |")
    if not years:
        lines.append("| (none) | 0 | |")
    lines.extend(["", _facet_markdown(entries, canonicalizer)])
    return "\n".join(lines).rstrip() + "\n"


def _year_doc(
    year: str,
    entries: list[IndexBEntry],
    months: dict[str, list[IndexBEntry]],
    date_from: str | None,
    date_to: str | None,
    canonicalizer: FacetCanonicalizer,
) -> str:
    lines = [
        _frontmatter(f"year:{year}", date_from, date_to, len(entries)),
        f"# Index B Year {year}",
        "",
        "## Child Nodes",
        "",
        "| month | count | doc |",
        "|---|---:|---|",
    ]
    for month, month_entries in sorted(months.items()):
        lines.append(
            f"| {year}-{month} | {len(month_entries)} | "
            f"{_doc_rel('Journals', year, month, 'index.md')} |"
        )
    lines.extend(["", _facet_markdown(entries, canonicalizer)])
    return "\n".join(lines).rstrip() + "\n"


def _month_doc(
    year: str,
    month: str,
    entries: list[IndexBEntry],
    date_from: str | None,
    date_to: str | None,
    canonicalizer: FacetCanonicalizer,
) -> str:
    lines = [
        _frontmatter(f"month:{year}-{month}", date_from, date_to, len(entries)),
        f"# Index B Month {year}-{month}",
        "",
        _entry_pointer_markdown(entries),
        _facet_markdown(entries, canonicalizer),
    ]
    return "\n".join(lines).rstrip() + "\n"


def _write_text(path: Path, text: str, *, dry_run: bool) -> None:
    if dry_run:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(path.name + ".tmp")
    tmp_path.write_text(text, encoding="utf-8")
    tmp_path.replace(path)


def _build_doc_specs(
    *,
    data_dir: Path,
    output_dir: Path,
    entries: list[IndexBEntry],
    years: dict[str, list[IndexBEntry]],
    months_by_year: dict[str, dict[str, list[IndexBEntry]]],
    date_from: str | None,
    date_to: str | None,
    canonicalizer: FacetCanonicalizer,
) -> list[IndexBDocSpec]:
    specs: list[IndexBDocSpec] = []

    root_path = output_dir / "INDEX.md"
    root_text = _root_doc(entries, years, date_from, date_to, canonicalizer)
    specs.append(
        IndexBDocSpec(
            key="root",
            path=root_path,
            rel_path=safe_relative_path(root_path, data_dir),
            text=root_text,
            entries=tuple(entries),
        )
    )

    for year, year_entries in sorted(years.items()):
        year_path = output_dir / "Journals" / year / "index.md"
        year_text = _year_doc(
            year, year_entries, months_by_year[year], date_from, date_to, canonicalizer
        )
        specs.append(
            IndexBDocSpec(
                key=f"year:{year}",
                path=year_path,
                rel_path=safe_relative_path(year_path, data_dir),
                text=year_text,
                entries=tuple(year_entries),
            )
        )
        for month, month_entries in sorted(months_by_year[year].items()):
            month_path = output_dir / "Journals" / year / month / "index.md"
            month_text = _month_doc(year, month, month_entries, date_from, date_to, canonicalizer)
            specs.append(
                IndexBDocSpec(
                    key=f"month:{year}-{month}",
                    path=month_path,
                    rel_path=safe_relative_path(month_path, data_dir),
                    text=month_text,
                    entries=tuple(month_entries),
                )
            )
    return specs


def _manifest_path(data_dir: Path) -> Path:
    return data_dir / INDEX_B_DIR / INDEX_B_MANIFEST


def _read_manifest(data_dir: Path) -> dict[str, Any] | None:
    path = _manifest_path(data_dir)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _build_manifest(
    *,
    data_dir: Path,
    date_from: str | None,
    date_to: str | None,
    specs: list[IndexBDocSpec],
    canonicalizer: FacetCanonicalizer,
) -> dict[str, Any]:
    scopes: dict[str, dict[str, Any]] = {}
    for spec in specs:
        scopes[spec.key] = {
            "doc": spec.rel_path,
            "entry_count": len(spec.entries),
            "source_hash": _source_hash(data_dir, spec.entries),
            "canonicalization_hash": canonicalizer.canonicalization_hash,
            "doc_hash": _sha256_text(spec.text),
        }
    return {
        "schema_version": INDEX_B_MANIFEST_SCHEMA_VERSION,
        "generated_at": _generated_at(),
        "artifact": "index-b",
        "date_from": date_from,
        "date_to": date_to,
        "scopes": scopes,
    }


def _compare_freshness(
    *,
    data_dir: Path,
    date_from: str | None,
    date_to: str | None,
    specs: list[IndexBDocSpec],
    canonicalizer: FacetCanonicalizer,
    manifest: dict[str, Any] | None,
) -> dict[str, Any]:
    expected_keys = {spec.key for spec in specs}
    stale_scopes: list[str] = []
    fresh_scopes: list[str] = []
    reasons: dict[str, str] = {}

    scopes = manifest.get("scopes", {}) if manifest else {}
    if not isinstance(scopes, dict):
        scopes = {}

    for spec in specs:
        recorded = scopes.get(spec.key)
        reason = ""
        if manifest is None:
            reason = "manifest_missing"
        elif manifest.get("date_from") != date_from or manifest.get("date_to") != date_to:
            reason = "range_mismatch"
        elif not isinstance(recorded, dict):
            reason = "scope_missing"
        elif not spec.path.exists():
            reason = "doc_missing"
        elif recorded.get("source_hash") != _source_hash(data_dir, spec.entries):
            reason = "source_hash_mismatch"
        elif recorded.get("canonicalization_hash") != canonicalizer.canonicalization_hash:
            reason = "canonicalization_hash_mismatch"
        elif recorded.get("doc_hash") != _sha256_text(spec.text):
            reason = "doc_hash_mismatch"

        if reason:
            stale_scopes.append(spec.key)
            reasons[spec.key] = reason
        else:
            fresh_scopes.append(spec.key)

    removed_scopes = sorted(set(scopes) - expected_keys)
    return {
        "fresh": not stale_scopes and not removed_scopes,
        "stale_scopes": stale_scopes,
        "fresh_scopes": fresh_scopes,
        "removed_scopes": removed_scopes,
        "reasons": reasons,
        "manifest_present": manifest is not None,
    }


def _plan_materialization(date_from: str | None, date_to: str | None) -> tuple[
    Path,
    Path,
    list[IndexBEntry],
    dict[str, list[IndexBEntry]],
    dict[str, dict[str, list[IndexBEntry]]],
    list[IndexBDocSpec],
    FacetCanonicalizer,
]:
    data_dir = get_user_data_dir()
    output_dir = data_dir / INDEX_B_DIR
    canonicalizer = load_facet_canonicalizer(data_dir)
    entries = _collect_entries(date_from, date_to)
    years: dict[str, list[IndexBEntry]] = defaultdict(list)
    months_by_year: dict[str, dict[str, list[IndexBEntry]]] = defaultdict(lambda: defaultdict(list))
    for entry in entries:
        years[entry.year].append(entry)
        months_by_year[entry.year][entry.month].append(entry)
    specs = _build_doc_specs(
        data_dir=data_dir,
        output_dir=output_dir,
        entries=entries,
        years=years,
        months_by_year=months_by_year,
        date_from=date_from,
        date_to=date_to,
        canonicalizer=canonicalizer,
    )
    return data_dir, output_dir, entries, years, months_by_year, specs, canonicalizer


def build_materialize_payload(
    *,
    date_from: str | None = None,
    date_to: str | None = None,
    dry_run: bool = False,
    incremental: bool = False,
) -> dict[str, Any]:
    """Build and optionally write deterministic Index B navigation docs."""
    start = _parse_month(date_from)
    end = _parse_month(date_to, fallback=start)
    if start is not None and end is not None and end < start:
        raise ValueError("--to must be greater than or equal to --from")

    data_dir, _output_dir, entries, years, months_by_year, specs, canonicalizer = (
        _plan_materialization(start, end)
    )
    freshness = _compare_freshness(
        data_dir=data_dir,
        date_from=start,
        date_to=end,
        specs=specs,
        canonicalizer=canonicalizer,
        manifest=_read_manifest(data_dir),
    )
    stale_scope_set = set(freshness["stale_scopes"])

    written_docs: list[str] = []
    skipped_fresh_docs: list[str] = []

    for spec in specs:
        if incremental and spec.key not in stale_scope_set:
            skipped_fresh_docs.append(spec.rel_path)
            continue
        _write_text(spec.path, spec.text, dry_run=dry_run)
        written_docs.append(spec.rel_path)

    manifest = _build_manifest(
        data_dir=data_dir,
        date_from=start,
        date_to=end,
        specs=specs,
        canonicalizer=canonicalizer,
    )
    manifest_path = _manifest_path(data_dir)
    if not dry_run:
        _write_text(
            manifest_path, json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", dry_run=False
        )
    written_docs.append(safe_relative_path(manifest_path, data_dir))

    return {
        "truth_source": "journals",
        "artifact": "index-b",
        "schema_version": INDEX_B_SCHEMA_VERSION,
        "generated_at": _generated_at(),
        "output_dir": INDEX_B_DIR,
        "date_from": start,
        "date_to": end,
        "entry_count": len(entries),
        "year_count": len(years),
        "month_count": sum(len(months) for months in months_by_year.values()),
        "facets": [spec.name for spec in FACETS],
        "canonicalization": canonicalizer.to_payload(),
        "written_docs": written_docs,
        "skipped_fresh_docs": skipped_fresh_docs,
        "incremental": incremental,
        "freshness_before": freshness,
        "dry_run": dry_run,
    }


def build_freshness_payload(
    *,
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict[str, Any]:
    """Return deterministic Index B freshness status for the selected range."""
    start = _parse_month(date_from)
    end = _parse_month(date_to, fallback=start)
    if start is not None and end is not None and end < start:
        raise ValueError("--to must be greater than or equal to --from")

    data_dir, _output_dir, entries, years, months_by_year, specs, canonicalizer = (
        _plan_materialization(start, end)
    )
    freshness = _compare_freshness(
        data_dir=data_dir,
        date_from=start,
        date_to=end,
        specs=specs,
        canonicalizer=canonicalizer,
        manifest=_read_manifest(data_dir),
    )
    return {
        "truth_source": "journals",
        "artifact": "index-b",
        "schema_version": INDEX_B_MANIFEST_SCHEMA_VERSION,
        "date_from": start,
        "date_to": end,
        "entry_count": len(entries),
        "year_count": len(years),
        "month_count": sum(len(months) for months in months_by_year.values()),
        "canonicalization": canonicalizer.to_payload(),
        **freshness,
    }


def _fallback_entries(entries: list[IndexBEntry]) -> list[dict[str, str]]:
    return [
        {
            "date": entry.date,
            "title": entry.title,
            "path": entry.rel_path,
        }
        for entry in entries
    ]


def build_ensure_payload(
    *,
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict[str, Any]:
    """Ensure Index B is fresh, falling back to journal pointers if refresh fails."""
    start = _parse_month(date_from)
    end = _parse_month(date_to, fallback=start)
    if start is not None and end is not None and end < start:
        raise ValueError("--to must be greater than or equal to --from")

    freshness = build_freshness_payload(date_from=start, date_to=end)
    if freshness["fresh"]:
        return {
            "source": "index-b",
            "artifact": "index-b",
            "date_from": start,
            "date_to": end,
            "freshness": freshness,
            "fallback": {"used": False, "reason": None},
        }

    try:
        materialized = build_materialize_payload(date_from=start, date_to=end, incremental=True)
        refreshed = build_freshness_payload(date_from=start, date_to=end)
        return {
            "source": "index-b",
            "artifact": "index-b",
            "date_from": start,
            "date_to": end,
            "freshness_before": freshness,
            "freshness": refreshed,
            "materialized": materialized,
            "fallback": {"used": False, "reason": None},
        }
    except Exception as exc:
        entries = _collect_entries(start, end)
        return {
            "source": "journals",
            "artifact": "index-b-fallback",
            "date_from": start,
            "date_to": end,
            "entry_count": len(entries),
            "entries": _fallback_entries(entries),
            "freshness_before": freshness,
            "fallback": {"used": True, "reason": str(exc)},
        }
