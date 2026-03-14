#!/usr/bin/env python3
"""
Life Index E2E Test Runner Package
====================================
Executes YAML-based E2E tests without requiring an Agent.

Usage:
    python -m tests.e2e.runner                    # Run all phases
    python -m tests.e2e.runner --phase 1          # Run specific phase
    python -m tests.e2e.runner --ci               # CI mode (JSON output, exit codes)
    python -m tests.e2e.runner --dry-run          # Show what would be executed
"""

from .runner import E2ETestRunner, TestResult, PhaseResult

__all__ = ["E2ETestRunner", "TestResult", "PhaseResult"]
