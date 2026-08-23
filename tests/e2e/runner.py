#!/usr/bin/env python3
"""
Life Index E2E Test Runner
===========================
Executes YAML-based E2E tests without requiring an Agent.

Usage:
    python -m tests.e2e.runner                    # Run all phases
    python -m tests.e2e.runner --phase 1          # Run specific phase
    python -m tests.e2e.runner --ci               # CI mode (JSON output, exit codes)
    python -m tests.e2e.runner --dry-run          # Show what would be executed
"""

import argparse
import json
import re
import subprocess
import sys
import time
import tempfile
import shutil
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml


@dataclass
class TestResult:
    """Result of a single test case execution."""

    id: str
    name: str
    phase: str
    passed: bool
    duration_ms: float
    error: str = ""
    details: Dict[str, Any] = field(default_factory=dict)
    performance: Dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PhaseResult:
    """Result of a test phase."""

    name: str
    passed: int = 0
    failed: int = 0
    cases: List[TestResult] = field(default_factory=list)

    @property
    def total(self) -> int:
        return self.passed + self.failed

    @property
    def pass_rate(self) -> float:
        return self.passed / self.total if self.total > 0 else 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "passed": self.passed,
            "failed": self.failed,
            "total": self.total,
            "pass_rate": round(self.pass_rate, 2),
            "cases": [c.to_dict() for c in self.cases],
        }


class E2ETestRunner:
    """
    E2E Test Runner for Life Index.

    Executes YAML test cases by calling tools via subprocess.
    """

    PHASES = {
        1: "phase1-core-workflow.yaml",
        2: "phase2-search-retrieval.yaml",
        3: "phase3-edge-cases.yaml",
        4: "phase4-edit-abstract.yaml",
    }

    def __init__(
        self,
        project_root: Optional[Path] = None,
        ci_mode: bool = False,
        dry_run: bool = False,
        cleanup: bool = True,
    ):
        self.project_root = project_root or Path(__file__).parent.parent.parent
        self.e2e_dir = self.project_root / "tests" / "e2e"
        self.reports_dir = self.project_root / "tests" / "reports"
        self.ci_mode = ci_mode
        self.dry_run = dry_run
        self.cleanup = cleanup
        self.created_files: List[Path] = []
        self.created_attachments: List[Path] = []
        self._temp_root = Path(tempfile.mkdtemp(prefix="life_index_e2e_"))
        self.test_data_dir = self._temp_root / "Life-Index"
        self.test_data_dir.mkdir(parents=True, exist_ok=True)

    def _build_env(self) -> Dict[str, str]:
        env = dict(__import__("os").environ)
        env["LIFE_INDEX_DATA_DIR"] = str(self.test_data_dir)
        return env

    def run_phase(self, phase_num: int) -> PhaseResult:
        """Run all test cases in a phase."""
        if phase_num not in self.PHASES:
            raise ValueError(f"Invalid phase: {phase_num}")

        yaml_file = self.e2e_dir / self.PHASES[phase_num]
        if not yaml_file.exists():
            raise FileNotFoundError(f"Phase file not found: {yaml_file}")

        try:
            with open(yaml_file, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
        except yaml.YAMLError as e:
            # Return a failed phase result for YAML parsing errors
            return PhaseResult(
                name=f"Phase {phase_num} (YAML Error)",
                failed=1,
                cases=[
                    TestResult(
                        id="YAML_PARSE_ERROR",
                        name=f"Failed to parse {yaml_file.name}",
                        phase=f"Phase {phase_num}",
                        passed=False,
                        duration_ms=0,
                        error=str(e),
                    )
                ],
            )

        phase_name = data.get("test_suite", {}).get("name", f"Phase {phase_num}")
        self.cleanup = data.get("test_suite", {}).get("cleanup_after_test", True)

        result = PhaseResult(name=phase_name)

        test_cases = data.get("test_cases", [])
        for case in test_cases:
            test_result = self.run_test_case(case, phase_name)
            result.cases.append(test_result)
            if test_result.passed:
                result.passed += 1
            else:
                result.failed += 1

        return result

    def _preprocess_test_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Preprocess test data to handle Python-style syntax in YAML.

        Handles patterns like:
        - content: "text" * 100  -> content: "texttext..." (repeated 100 times)
        """
        result = {}
        for key, value in data.items():
            if isinstance(value, str):
                # Handle Python-style string multiplication
                # Pattern: "text" * N or 'text' * N
                match = re.match(r'^["\'](.+?)["\']\s*\*\s*(\d+)$', value.strip())
                if match:
                    text = match.group(1)
                    count = int(match.group(2))
                    result[key] = text * count
                else:
                    result[key] = value
            elif isinstance(value, dict):
                result[key] = self._preprocess_test_data(value)
            elif isinstance(value, list):
                result[key] = [
                    self._preprocess_test_data(item) if isinstance(item, dict) else item
                    for item in value
                ]
            else:
                result[key] = value
        return result

    def run_test_case(self, case: Dict[str, Any], phase_name: str) -> TestResult:
        """Run a single test case."""
        case_id = case.get("id", "unknown")
        name = case.get("name", "unnamed")

        if self.dry_run:
            print(f"  [DRY-RUN] Would execute: {case_id} - {name}")
            return TestResult(
                id=case_id,
                name=name,
                phase=phase_name,
                passed=True,
                duration_ms=0,
                details={"dry_run": True},
            )

        print(f"  Running: {case_id} - {name}")
        start_time = time.perf_counter()

        try:
            # Handle multi-step tests
            if "steps" in case:
                result = self._run_multi_step_test(case)
            else:
                result = self._run_single_test(case)

            duration_ms = (time.perf_counter() - start_time) * 1000

            return TestResult(
                id=case_id,
                name=name,
                phase=phase_name,
                passed=result["passed"],
                duration_ms=round(duration_ms, 2),
                error=result.get("error", ""),
                details=result.get("details", {}),
                performance=result.get("performance", {}),
            )

        except Exception as e:
            duration_ms = (time.perf_counter() - start_time) * 1000
            return TestResult(
                id=case_id,
                name=name,
                phase=phase_name,
                passed=False,
                duration_ms=round(duration_ms, 2),
                error=str(e),
            )

    def _run_single_test(self, case: Dict[str, Any]) -> Dict[str, Any]:
        """Run a single-step test case."""
        input_data = case.get("input", {})
        expected = case.get("expected", {})

        # Determine which tool to call
        if "extract" in input_data or "data" in input_data:
            # write_journal test
            return self._test_write_journal(input_data, expected)
        elif "query" in input_data or "query_params" in input_data:
            # search or other tool test
            action = input_data.get("action", "search")
            if action == "search":
                return self._test_search(input_data, expected)

        return {"passed": False, "error": "Unknown test action"}

    def _run_multi_step_test(self, case: Dict[str, Any]) -> Dict[str, Any]:
        """Run a multi-step test case."""
        steps = case.get("steps", [])

        last_journal_path = None
        all_passed = True
        errors = []

        for step in steps:
            action = step.get("action")

            if action == "write_journal":
                result = self._test_write_journal(
                    step.get("data", {}), step.get("expected", {})
                )
                if not result["passed"]:
                    all_passed = False
                    errors.append(f"Step {step.get('step')}: {result.get('error')}")
                elif "journal_path" in result.get("details", {}):
                    last_journal_path = result["details"]["journal_path"]

            elif action == "edit_journal":
                journal_ref = step.get("journal") or (
                    last_journal_path if step.get("use_last_created") else None
                )
                if not journal_ref:
                    return {"passed": False, "error": "No journal to edit"}
                result = self._test_edit_journal(
                    journal_ref, step.get("operations", []), step.get("expected", {})
                )
                if not result["passed"]:
                    all_passed = False
                    errors.append(f"Step {step.get('step')}: {result.get('error')}")

            elif action == "search":
                result = self._test_search(
                    step.get("query_params", {}), step.get("expected", {})
                )
                if not result["passed"]:
                    all_passed = False
                    errors.append(f"Step {step.get('step')}: {result.get('error')}")

            elif action in ("generate_abstract", "generate_index"):
                result = self._test_generate_abstract(
                    step.get("period"), step.get("value"), step.get("expected", {})
                )
                if not result["passed"]:
                    all_passed = False
                    errors.append(f"Step {step.get('step')}: {result.get('error')}")

            else:
                all_passed = False
                errors.append(
                    f"Step {step.get('step')}: Unknown step action '{action}'"
                )

        return {"passed": all_passed, "error": "; ".join(errors) if errors else ""}

    def _test_write_journal(
        self, input_data: Dict[str, Any], expected: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Test write_journal tool."""
        extract = input_data.get("extract") or input_data.get("data") or input_data

        # Preprocess to handle Python-style syntax
        extract = self._preprocess_test_data(extract)

        # Build command
        cmd = [
            sys.executable,
            "-m",
            "tools.write_journal",
            "--data",
            json.dumps(extract),
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=str(self.project_root),
                env=self._build_env(),
                timeout=30,
                encoding="utf-8",
            )

            if result.returncode != 0:
                return {"passed": False, "error": f"Tool failed: {result.stderr}"}

            output = self._parse_json_output(result.stdout)

            # Validate results
            validation = self._validate_output(output, expected)

            if output.get("success") and output.get("journal_path"):
                self.created_files.append(Path(output["journal_path"]))
                for attachment in output.get("attachments", []) or []:
                    rel_path = (
                        attachment.get("rel_path")
                        if isinstance(attachment, dict)
                        else None
                    )
                    if rel_path:
                        self.created_attachments.append(
                            (self.test_data_dir / Path(rel_path)).resolve()
                        )

            return {
                "passed": validation["passed"],
                "error": validation.get("error", ""),
                "details": output,
            }

        except subprocess.TimeoutExpired:
            return {"passed": False, "error": "Tool timeout (>30s)"}
        except json.JSONDecodeError as e:
            return {"passed": False, "error": f"Invalid JSON output: {e}"}

    def _test_search(
        self, input_data: Dict[str, Any], expected: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Test search_journals tool."""
        query_params = dict(input_data.get("query_params", {}))
        merged_input = {k: v for k, v in input_data.items() if k != "query_params"}
        merged_input.update(query_params)

        cmd = [sys.executable, "-m", "tools.search_journals"]

        if "query" in merged_input:
            cmd.extend(["--query", str(merged_input["query"])])
        if "topic" in merged_input:
            cmd.extend(["--topic", str(merged_input["topic"])])
        if "project" in merged_input:
            cmd.extend(["--project", str(merged_input["project"])])
        if "tags" in merged_input:
            tags = merged_input["tags"]
            if isinstance(tags, list):
                tags = ",".join(str(tag) for tag in tags)
            cmd.extend(["--tags", str(tags)])
        if "mood" in merged_input:
            mood = merged_input["mood"]
            if isinstance(mood, list):
                mood = ",".join(str(item) for item in mood)
            cmd.extend(["--mood", str(mood)])
        if "people" in merged_input:
            people = merged_input["people"]
            if isinstance(people, list):
                people = ",".join(str(item) for item in people)
            cmd.extend(["--people", str(people)])
        if "date_from" in merged_input:
            cmd.extend(["--date-from", str(merged_input["date_from"])])
        if "date_to" in merged_input:
            cmd.extend(["--date-to", str(merged_input["date_to"])])
        if "location" in merged_input:
            cmd.extend(["--location", str(merged_input["location"])])
        if "weather" in merged_input:
            cmd.extend(["--weather", str(merged_input["weather"])])
        if "level" in merged_input:
            cmd.extend(["--level", str(merged_input["level"])])
        if "limit" in merged_input:
            cmd.extend(["--limit", str(merged_input["limit"])])

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=str(self.project_root),
                env=self._build_env(),
                timeout=30,
                encoding="utf-8",
            )

            if result.returncode != 0:
                return {"passed": False, "error": f"Tool failed: {result.stderr}"}

            output = self._parse_json_output(result.stdout)
            validation = self._validate_output(output, expected)

            return {
                "passed": validation["passed"],
                "error": validation.get("error", ""),
                "details": output,
            }

        except subprocess.TimeoutExpired:
            return {"passed": False, "error": "Tool timeout (>30s)"}
        except json.JSONDecodeError as e:
            return {"passed": False, "error": f"Invalid JSON output: {e}"}

    def _test_edit_journal(
        self, journal: str, operations: List[Dict[str, Any]], expected: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Test edit_journal tool."""
        cmd = [sys.executable, "-m", "tools.edit_journal", "--journal", journal]

        for op in operations:
            for key, value in op.items():
                flag = f"--{key.replace('_', '-')}"
                cmd.extend([flag, str(value)])

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=str(self.project_root),
                env=self._build_env(),
                timeout=30,
                encoding="utf-8",
            )

            if result.returncode != 0:
                return {"passed": False, "error": f"Tool failed: {result.stderr}"}

            output = self._parse_json_output(result.stdout)
            validation = self._validate_output(output, expected)

            return {
                "passed": validation["passed"],
                "error": validation.get("error", ""),
                "details": output,
            }

        except subprocess.TimeoutExpired:
            return {"passed": False, "error": "Tool timeout (>30s)"}
        except json.JSONDecodeError as e:
            return {"passed": False, "error": f"Invalid JSON output: {e}"}

    def _test_generate_abstract(
        self, period: Optional[str], value: Optional[str], expected: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Test generate_index tool."""
        cmd = [sys.executable, "-m", "tools.generate_index", "--json"]

        if period == "month" and value:
            cmd.extend(["--month", str(value)])
        elif period == "year" and value:
            cmd.extend(["--year", str(value)])
        else:
            return {"passed": False, "error": "Invalid abstract generation params"}

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=str(self.project_root),
                env=self._build_env(),
                timeout=30,
                encoding="utf-8",
            )

            if result.returncode != 0:
                return {"passed": False, "error": f"Tool failed: {result.stderr}"}

            output = self._parse_json_output(result.stdout)
            if isinstance(output, list):
                output = output[0] if output else {}

            validation = self._validate_output(output, expected)

            return {
                "passed": validation["passed"],
                "error": validation.get("error", ""),
                "details": output,
            }

        except subprocess.TimeoutExpired:
            return {"passed": False, "error": "Tool timeout (>30s)"}
        except json.JSONDecodeError as e:
            return {"passed": False, "error": f"Invalid JSON output: {e}"}

    def _parse_json_output(self, stdout: str) -> Any:
        """Extract JSON payload from mixed stdout text."""
        text = stdout.strip()
        if not text:
            raise json.JSONDecodeError("Empty output", stdout, 0)

        first_brace = text.find("{")
        last_brace = text.rfind("}")
        if first_brace == -1 or last_brace == -1 or last_brace < first_brace:
            raise json.JSONDecodeError("No JSON object found", stdout, 0)

        payload = text[first_brace : last_brace + 1]
        return json.loads(payload)

    def _resolve_expected_value(self, output: Dict[str, Any], key: str) -> Any:
        """Map legacy E2E expectation keys to current tool output."""
        alias_map = {
            "journal_created": bool(output.get("journal_path")),
            "location": output.get("location_used"),
            "weather": output.get("weather_used"),
            "final_location": output.get("changes", {}).get("location", {}).get("new"),
            "final_weather": output.get("changes", {}).get("weather", {}).get("new"),
        }
        if key in alias_map:
            return alias_map[key]
        return output.get(key)

    def _validate_output(
        self, output: Dict[str, Any], expected: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Validate tool output against expected values."""
        errors = []
        merged_results = output.get("merged_results", []) or []

        for key, expected_value in expected.items():
            if key == "results_count":
                actual_count = len(merged_results)
                if isinstance(expected_value, str):
                    match = re.match(r"^(>=|<=|>|<)\s*(\d+)$", expected_value.strip())
                    if match:
                        op, threshold = match.groups()
                        threshold_int = int(threshold)
                        comparisons = {
                            ">=": actual_count >= threshold_int,
                            "<=": actual_count <= threshold_int,
                            ">": actual_count > threshold_int,
                            "<": actual_count < threshold_int,
                        }
                        if not comparisons[op]:
                            errors.append(
                                f"{key}: expected {expected_value}, got {actual_count}"
                            )
                        continue
                if actual_count != expected_value:
                    errors.append(
                        f"{key}: expected {expected_value}, got {actual_count}"
                    )
                continue

            if key == "contains_titles":
                titles = [str(item.get("title", "")) for item in merged_results]
                for expected_title in expected_value:
                    if not any(expected_title in title for title in titles):
                        errors.append(f"contains_titles: missing {expected_title}")
                continue

            if key == "highlights_contain":
                snippets = [str(item.get("snippet", "")) for item in merged_results]
                if not any(str(expected_value) in snippet for snippet in snippets):
                    errors.append(f"highlights_contain: missing {expected_value}")
                continue

            if key == "all_results_match_tags":
                for item in merged_results:
                    item_tags = (
                        item.get("tags") or item.get("metadata", {}).get("tags") or []
                    )
                    for expected_tag in expected_value:
                        if expected_tag not in item_tags:
                            errors.append(
                                f"all_results_match_tags: result {item.get('rel_path', item.get('path', 'unknown'))} missing {expected_tag}"
                            )
                            break
                continue

            actual_value = self._resolve_expected_value(output, key)

            # Handle special matchers
            if isinstance(expected_value, str):
                match = re.match(
                    r"^(>=|<=|>|<)\s*(-?\d+(?:\.\d+)?)$", expected_value.strip()
                )
                if match and isinstance(actual_value, (int, float)):
                    op, threshold = match.groups()
                    threshold_num = float(threshold)
                    actual_num = float(actual_value)
                    comparisons = {
                        ">=": actual_num >= threshold_num,
                        "<=": actual_num <= threshold_num,
                        ">": actual_num > threshold_num,
                        "<": actual_num < threshold_num,
                    }
                    if not comparisons[op]:
                        errors.append(
                            f"{key}: expected {expected_value}, got {actual_value}"
                        )
                    continue
                if expected_value == "(非空字符串)" or expected_value == "(non-empty)":
                    if not actual_value:
                        errors.append(f"{key}: expected non-empty, got empty")
                    continue
                if expected_value.startswith("(") and expected_value.endswith(")"):
                    # Description matcher - skip validation
                    continue

            # Handle None expected
            if expected_value is None:
                if actual_value is not None:
                    errors.append(f"{key}: expected None, got {actual_value}")
                continue

            # Handle boolean
            if isinstance(expected_value, bool):
                if actual_value != expected_value:
                    errors.append(
                        f"{key}: expected {expected_value}, got {actual_value}"
                    )
                continue

            # Handle string/number comparison
            if actual_value != expected_value:
                errors.append(f"{key}: expected {expected_value}, got {actual_value}")

        return {
            "passed": len(errors) == 0,
            "error": "; ".join(errors) if errors else "",
        }

    def run_all(self, phases: Optional[List[int]] = None) -> Dict[str, Any]:
        """Run all specified phases."""
        phases = phases or list(self.PHASES.keys())

        results = []
        for phase_num in phases:
            print(f"\n=== Running Phase {phase_num} ===")
            result = self.run_phase(phase_num)
            results.append(result)

        # Calculate totals
        total_passed = sum(r.passed for r in results)
        total_failed = sum(r.failed for r in results)
        total_cases = total_passed + total_failed

        summary = {
            "timestamp": datetime.now().isoformat(),
            "summary": {
                "total": total_cases,
                "passed": total_passed,
                "failed": total_failed,
                "pass_rate": round(total_passed / total_cases, 2)
                if total_cases > 0
                else 0,
            },
            "phases": [r.to_dict() for r in results],
        }

        # Generate reports
        self._generate_reports(summary)

        # Cleanup if enabled
        if self.cleanup and not self.dry_run:
            self._cleanup()

        return summary

    def _generate_reports(self, summary: Dict[str, Any]) -> None:
        """Generate Markdown and JSON reports."""
        self.reports_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")

        # JSON report (for CI)
        json_path = self.reports_dir / f"e2e-report-{timestamp}.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)
        print(f"\nJSON report: {json_path}")

        # Markdown report
        md_path = self.reports_dir / f"e2e-report-{timestamp}.md"
        md_content = self._generate_markdown_report(summary)
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(md_content)
        print(f"Markdown report: {md_path}")

    def _generate_markdown_report(self, summary: Dict[str, Any]) -> str:
        """Generate Markdown report content."""
        lines = [
            "# E2E Test Report",
            "",
            f"**Timestamp**: {summary['timestamp']}",
            "",
            "## Summary",
            "",
            f"- Total: {summary['summary']['total']}",
            f"- Passed: {summary['summary']['passed']} ✅",
            f"- Failed: {summary['summary']['failed']} ❌",
            f"- Pass Rate: {summary['summary']['pass_rate'] * 100:.1f}%",
            "",
        ]

        for phase in summary["phases"]:
            lines.extend(
                [
                    f"## {phase['name']}",
                    "",
                    "| ID | Name | Status | Duration |",
                    "|----|------|--------|----------|",
                ]
            )

            for case in phase["cases"]:
                status = "✅" if case["passed"] else "❌"
                duration = f"{case['duration_ms']:.0f}ms"
                lines.append(
                    f"| {case['id']} | {case['name']} | {status} | {duration} |"
                )

            lines.append("")

        return "\n".join(lines)

    def _cleanup(self) -> None:
        """Clean up test-generated files."""
        if not self.created_files:
            return

        print(f"\nCleaning up {len(self.created_files)} test files...")
        for path in self.created_files:
            try:
                if path.exists():
                    path.unlink()
            except Exception as e:
                print(f"  Warning: Could not delete {path}: {e}")

        for path in self.created_attachments:
            try:
                if path.exists():
                    path.unlink()
            except Exception as e:
                print(f"  Warning: Could not delete {path}: {e}")

        if self._temp_root.exists():
            shutil.rmtree(self._temp_root, ignore_errors=True)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Life Index E2E Test Runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python -m tests.e2e.runner                    # Run all phases
    python -m tests.e2e.runner --phase 1 2        # Run phases 1 and 2
    python -m tests.e2e.runner --ci               # CI mode
    python -m tests.e2e.runner --dry-run          # Show what would be executed
        """,
    )

    parser.add_argument(
        "--phase",
        "-p",
        type=int,
        nargs="+",
        choices=[1, 2, 3, 4],
        help="Run specific phase(s)",
    )
    parser.add_argument(
        "--ci", action="store_true", help="CI mode (JSON output to stdout, exit codes)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be executed without running",
    )
    parser.add_argument(
        "--no-cleanup", action="store_true", help="Don't clean up test files after run"
    )

    args = parser.parse_args()

    runner = E2ETestRunner(
        ci_mode=args.ci, dry_run=args.dry_run, cleanup=not args.no_cleanup
    )

    try:
        summary = runner.run_all(args.phase)

        if args.ci:
            # CI mode: output JSON to stdout
            print(json.dumps(summary, indent=2))

        # Exit with non-zero if any tests failed
        if summary["summary"]["failed"] > 0:
            sys.exit(1)

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
