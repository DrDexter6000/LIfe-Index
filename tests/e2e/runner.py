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
        if "extract" in input_data:
            # write_journal test
            return self._test_write_journal(input_data, expected)
        elif "query" in input_data or "data" in input_data:
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

        return {"passed": all_passed, "error": "; ".join(errors) if errors else ""}

    def _test_write_journal(
        self, input_data: Dict[str, Any], expected: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Test write_journal tool."""
        extract = input_data.get("extract", input_data)

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
                timeout=30,
            )

            if result.returncode != 0:
                return {"passed": False, "error": f"Tool failed: {result.stderr}"}

            output = json.loads(result.stdout)

            # Validate results
            validation = self._validate_output(output, expected)

            if output.get("success") and output.get("journal_path"):
                self.created_files.append(Path(output["journal_path"]))

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
        cmd = [sys.executable, "-m", "tools.search_journals"]

        if "query" in input_data:
            cmd.extend(["--query", input_data["query"]])
        if "topic" in input_data:
            cmd.extend(["--topic", input_data["topic"]])
        if "level" in input_data:
            cmd.extend(["--level", str(input_data["level"])])

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=str(self.project_root),
                timeout=30,
            )

            if result.returncode != 0:
                return {"passed": False, "error": f"Tool failed: {result.stderr}"}

            output = json.loads(result.stdout)
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
                timeout=30,
            )

            if result.returncode != 0:
                return {"passed": False, "error": f"Tool failed: {result.stderr}"}

            output = json.loads(result.stdout)
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

    def _validate_output(
        self, output: Dict[str, Any], expected: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Validate tool output against expected values."""
        errors = []

        for key, expected_value in expected.items():
            actual_value = output.get(key)

            # Handle special matchers
            if isinstance(expected_value, str):
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
        choices=[1, 2, 3],
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
