#!/usr/bin/env python3
"""E2E Acceptance Test Runner for Syn137.

This script runs automated acceptance tests for features F8-F12 (Agentic Integration).
For F1-F7 (Infrastructure, CLI, API, Frontend), use manual validation or dedicated scripts.

Usage:
    python scripts/e2e_acceptance_tests.py [--feature F8] [--live]

Options:
    --feature   Run tests for a specific feature (F8, F9, F10, F11, F12, or "all")
    --live      Run live agent tests (requires ANTHROPIC_API_KEY)
    --verbose   Show detailed test output
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum


class TestStatus(Enum):
    """Test result status."""

    PASSED = "✅"
    FAILED = "❌"
    SKIPPED = "⏭️"
    RUNNING = "🔄"


@dataclass
class TestResult:
    """Result of a single test criterion."""

    criterion_id: str
    description: str
    status: TestStatus
    message: str = ""
    duration_ms: float = 0.0


@dataclass
class FeatureResult:
    """Result of a feature test suite."""

    feature_id: str
    feature_name: str
    results: list[TestResult] = field(default_factory=list)

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.status == TestStatus.PASSED)

    @property
    def failed(self) -> int:
        return sum(1 for r in self.results if r.status == TestStatus.FAILED)

    @property
    def skipped(self) -> int:
        return sum(1 for r in self.results if r.status == TestStatus.SKIPPED)

    @property
    def total(self) -> int:
        return len(self.results)


def print_header(text: str) -> None:
    """Print a formatted header."""
    print(f"\n{'=' * 60}")
    print(f"  {text}")
    print(f"{'=' * 60}")


def print_result(result: TestResult) -> None:
    """Print a single test result."""
    status_icon = result.status.value
    print(f"  {status_icon} {result.criterion_id}: {result.description}")
    if result.message:
        print(f"      → {result.message}")


def run_pytest(
    test_path: str, pattern: str | None = None, verbose: bool = False
) -> tuple[bool, str]:
    """Run pytest for a specific test file/pattern.

    Returns:
        Tuple of (success, output)
    """
    cmd = ["python", "-m", "pytest", test_path, "-v"]
    if pattern:
        cmd.extend(["-k", pattern])
    if not verbose:
        cmd.append("-q")

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        output = result.stdout + result.stderr
        return result.returncode == 0, output
    except subprocess.TimeoutExpired:
        return False, "Test timed out after 300 seconds"
    except Exception as e:
        return False, str(e)


# =============================================================================
# F8: Agentic Workflow Execution Tests
# =============================================================================


def test_f8_agentic_execution(verbose: bool = False, live: bool = False) -> FeatureResult:
    """Run F8: Agentic Workflow Execution tests."""
    feature = FeatureResult(
        feature_id="F8",
        feature_name="Agentic Workflow Execution",
    )

    print_header("F8: Agentic Workflow Execution")

    # F8.1 - Executor Initialization
    print("\n  F8.1 AgenticWorkflowExecutor Initialization")
    success, output = run_pytest(
        "packages/syn-adapters/tests/test_orchestration.py",
        "test_executor",
        verbose,
    )
    feature.results.append(
        TestResult(
            criterion_id="8.1.1-4",
            description="Executor initialization with dependencies",
            status=TestStatus.PASSED if success else TestStatus.FAILED,
            message=output if not success else "",
        )
    )
    print_result(feature.results[-1])

    # F8.2 - Single-Phase Execution
    print("\n  F8.2 Single-Phase Workflow Execution")
    success, output = run_pytest(
        "packages/syn-adapters/tests/test_orchestration.py",
        "test_execute_simple",
        verbose,
    )
    feature.results.append(
        TestResult(
            criterion_id="8.2.1-6",
            description="Single-phase workflow execution",
            status=TestStatus.PASSED if success else TestStatus.FAILED,
            message=output if not success else "",
        )
    )
    print_result(feature.results[-1])

    # F8.3 - Multi-Phase Execution
    print("\n  F8.3 Multi-Phase Workflow Execution")
    success, output = run_pytest(
        "packages/syn-adapters/tests/test_orchestration.py",
        "test_execute_multi",
        verbose,
    )
    feature.results.append(
        TestResult(
            criterion_id="8.3.1-5",
            description="Multi-phase workflow with context passing",
            status=TestStatus.PASSED if success else TestStatus.FAILED,
            message=output if not success else "",
        )
    )
    print_result(feature.results[-1])

    # F8.4 - Failure Handling
    print("\n  F8.4 Execution Failure Handling")
    success, output = run_pytest(
        "packages/syn-adapters/tests/test_orchestration.py",
        "test_phase_failure",
        verbose,
    )
    feature.results.append(
        TestResult(
            criterion_id="8.4.1-5",
            description="Phase failure handling",
            status=TestStatus.PASSED if success else TestStatus.FAILED,
            message=output if not success else "",
        )
    )
    print_result(feature.results[-1])

    # F8.5 - Live Agent Execution (optional)
    print("\n  F8.5 Live Agent Execution")
    if not live:
        feature.results.append(
            TestResult(
                criterion_id="8.5.1-4",
                description="Live Claude agent execution",
                status=TestStatus.SKIPPED,
                message="Use --live flag to run (requires ANTHROPIC_API_KEY)",
            )
        )
    elif not os.environ.get("ANTHROPIC_API_KEY"):
        feature.results.append(
            TestResult(
                criterion_id="8.5.1-4",
                description="Live Claude agent execution",
                status=TestStatus.SKIPPED,
                message="ANTHROPIC_API_KEY not set",
            )
        )
    else:
        # Run live test
        success, output = run_pytest(
            "packages/syn-adapters/tests/test_claude_agentic.py",
            "test_live",
            verbose,
        )
        feature.results.append(
            TestResult(
                criterion_id="8.5.1-4",
                description="Live Claude agent execution",
                status=TestStatus.PASSED if success else TestStatus.FAILED,
                message=output if not success else "",
            )
        )
    print_result(feature.results[-1])

    return feature


# =============================================================================
# F9: Workspace & Hook Integration Tests
# =============================================================================


def test_f9_workspace_hooks(verbose: bool = False) -> FeatureResult:
    """Run F9: Workspace & Hook Integration tests."""
    feature = FeatureResult(
        feature_id="F9",
        feature_name="Workspace & Hook Integration",
    )

    print_header("F9: Workspace & Hook Integration")

    # F9.1 - LocalWorkspace Creation
    print("\n  F9.1 LocalWorkspace Creation")
    success, output = run_pytest(
        "packages/syn-adapters/tests/test_workspaces.py",
        "test_local_workspace",
        verbose,
    )
    feature.results.append(
        TestResult(
            criterion_id="9.1.1-5",
            description="LocalWorkspace creation and structure",
            status=TestStatus.PASSED if success else TestStatus.FAILED,
            message=output if not success else "",
        )
    )
    print_result(feature.results[-1])

    # F9.2 - Hook Settings
    print("\n  F9.2 Hook Settings Generation")
    success, output = run_pytest(
        "packages/syn-adapters/tests/test_workspaces.py",
        "test_hook_settings",
        verbose,
    )
    feature.results.append(
        TestResult(
            criterion_id="9.2.1-4",
            description="Hook settings.json generation",
            status=TestStatus.PASSED if success else TestStatus.FAILED,
            message=output if not success else "",
        )
    )
    print_result(feature.results[-1])

    # F9.3 - Analytics File
    print("\n  F9.3 Analytics JSONL File")
    success, output = run_pytest(
        "packages/syn-adapters/tests/test_workspaces.py",
        "test_analytics",
        verbose,
    )
    feature.results.append(
        TestResult(
            criterion_id="9.3.1-4",
            description="Analytics JSONL file creation",
            status=TestStatus.PASSED if success else TestStatus.FAILED,
            message=output if not success else "",
        )
    )
    print_result(feature.results[-1])

    # F9.4 - Context Injection
    print("\n  F9.4 Context Injection")
    success, output = run_pytest(
        "packages/syn-adapters/tests/test_workspaces.py",
        "test_inject",
        verbose,
    )
    feature.results.append(
        TestResult(
            criterion_id="9.4.1-3",
            description="Context injection into workspace",
            status=TestStatus.PASSED if success else TestStatus.FAILED,
            message=output if not success else "",
        )
    )
    print_result(feature.results[-1])

    return feature


# =============================================================================
# F10: Artifact Bundle Flow Tests
# =============================================================================


def test_f10_artifacts(verbose: bool = False) -> FeatureResult:
    """Run F10: Artifact Bundle Flow tests."""
    feature = FeatureResult(
        feature_id="F10",
        feature_name="Artifact Bundle Flow",
    )

    print_header("F10: Artifact Bundle Flow")

    # F10.1 - ArtifactBundle Creation
    print("\n  F10.1 ArtifactBundle Creation")
    success, output = run_pytest(
        "packages/syn-adapters/tests/test_artifacts.py",
        "test_artifact_bundle or test_artifact_file",
        verbose,
    )
    feature.results.append(
        TestResult(
            criterion_id="10.1.1-5",
            description="ArtifactBundle creation with metadata",
            status=TestStatus.PASSED if success else TestStatus.FAILED,
            message=output if not success else "",
        )
    )
    print_result(feature.results[-1])

    # F10.2 - Directory Collection
    print("\n  F10.2 Directory Collection")
    success, output = run_pytest(
        "packages/syn-adapters/tests/test_artifacts.py",
        "test_from_directory",
        verbose,
    )
    feature.results.append(
        TestResult(
            criterion_id="10.2.1-5",
            description="Recursive file collection from directory",
            status=TestStatus.PASSED if success else TestStatus.FAILED,
            message=output if not success else "",
        )
    )
    print_result(feature.results[-1])

    # F10.3 - Serialization
    print("\n  F10.3 Serialization / Deserialization")
    success, output = run_pytest(
        "packages/syn-adapters/tests/test_artifacts.py",
        "test_serialization",
        verbose,
    )
    feature.results.append(
        TestResult(
            criterion_id="10.3.1-3",
            description="Bundle serialization round-trip",
            status=TestStatus.PASSED if success else TestStatus.FAILED,
            message=output if not success else "",
        )
    )
    print_result(feature.results[-1])

    # F10.4 - PhaseContext
    print("\n  F10.4 PhaseContext Creation")
    success, output = run_pytest(
        "packages/syn-adapters/tests/test_artifacts.py",
        "test_phase_context",
        verbose,
    )
    feature.results.append(
        TestResult(
            criterion_id="10.4.1-4",
            description="PhaseContext with previous artifacts",
            status=TestStatus.PASSED if success else TestStatus.FAILED,
            message=output if not success else "",
        )
    )
    print_result(feature.results[-1])

    return feature


# =============================================================================
# F11: Event Bridge Tests
# =============================================================================


def test_f11_event_bridge(verbose: bool = False) -> FeatureResult:
    """Run F11: Event Bridge tests."""
    feature = FeatureResult(
        feature_id="F11",
        feature_name="Event Bridge",
    )

    print_header("F11: Event Bridge")

    # F11.1 - JSONLWatcher
    print("\n  F11.1 JSONLWatcher")
    success, output = run_pytest(
        "packages/syn-adapters/tests/test_events.py",
        "TestJSONLWatcher",
        verbose,
    )
    feature.results.append(
        TestResult(
            criterion_id="11.1.1-4",
            description="JSONL file watching and parsing",
            status=TestStatus.PASSED if success else TestStatus.FAILED,
            message=output if not success else "",
        )
    )
    print_result(feature.results[-1])

    # F11.2 - Translator
    print("\n  F11.2 HookToDomainTranslator")
    success, output = run_pytest(
        "packages/syn-adapters/tests/test_events.py",
        "TestHookToDomainTranslator",
        verbose,
    )
    feature.results.append(
        TestResult(
            criterion_id="11.2.1-7",
            description="Hook to domain event translation",
            status=TestStatus.PASSED if success else TestStatus.FAILED,
            message=output if not success else "",
        )
    )
    print_result(feature.results[-1])

    # F11.3 - Bridge Integration
    print("\n  F11.3 EventBridge Integration")
    success, output = run_pytest(
        "packages/syn-adapters/tests/test_events.py",
        "TestEventBridge",
        verbose,
    )
    feature.results.append(
        TestResult(
            criterion_id="11.3.1-5",
            description="Event bridge to store integration",
            status=TestStatus.PASSED if success else TestStatus.FAILED,
            message=output if not success else "",
        )
    )
    print_result(feature.results[-1])

    return feature


# =============================================================================
# F12: Agent Provider Management Tests
# =============================================================================


def test_f12_providers(verbose: bool = False) -> FeatureResult:
    """Run F12: Agent Provider Management tests."""
    feature = FeatureResult(
        feature_id="F12",
        feature_name="Agent Provider Management",
    )

    print_header("F12: Agent Provider Management")

    # F12.1 - Agent Factory
    print("\n  F12.1 Agent Factory")
    success, output = run_pytest(
        "packages/syn-adapters/tests/test_orchestration.py",
        "test_agent_factory",
        verbose,
    )
    feature.results.append(
        TestResult(
            criterion_id="12.1.1-3",
            description="Agent factory provider lookup",
            status=TestStatus.PASSED if success else TestStatus.FAILED,
            message=output if not success else "",
        )
    )
    print_result(feature.results[-1])

    # F12.2 - Agent Availability
    print("\n  F12.2 Agent Availability")
    success, output = run_pytest(
        "packages/syn-adapters/tests/test_claude_agentic.py",
        "test_availability",
        verbose,
    )
    feature.results.append(
        TestResult(
            criterion_id="12.2.1-3",
            description="Agent availability checks",
            status=TestStatus.PASSED if success else TestStatus.FAILED,
            message=output if not success else "",
        )
    )
    print_result(feature.results[-1])

    # F12.3 - MockAgent Safety
    print("\n  F12.3 MockAgent Safety")
    success, output = run_pytest(
        "packages/syn-adapters/tests/test_mock.py",
        "test_mock_agent_environment",
        verbose,
    )
    feature.results.append(
        TestResult(
            criterion_id="12.3.1-3",
            description="MockAgent environment validation",
            status=TestStatus.PASSED if success else TestStatus.FAILED,
            message=output if not success else "",
        )
    )
    print_result(feature.results[-1])

    return feature


# =============================================================================
# Main Execution
# =============================================================================


def print_summary(results: list[FeatureResult]) -> None:
    """Print test summary table."""
    print_header("TEST RESULTS SUMMARY")

    total_passed = sum(f.passed for f in results)
    total_failed = sum(f.failed for f in results)
    total_skipped = sum(f.skipped for f in results)
    total = sum(f.total for f in results)

    print(f"\n{'Feature':<35} {'Total':>8} {'Passed':>8} {'Failed':>8} {'Skipped':>8}")
    print("-" * 75)

    for feature in results:
        status = "✅" if feature.failed == 0 else "❌"
        print(
            f"{status} {feature.feature_id}: {feature.feature_name:<25} "
            f"{feature.total:>8} {feature.passed:>8} {feature.failed:>8} {feature.skipped:>8}"
        )

    print("-" * 75)
    overall_status = "✅" if total_failed == 0 else "❌"
    print(
        f"{overall_status} {'TOTAL':<35} {total:>8} {total_passed:>8} {total_failed:>8} {total_skipped:>8}"
    )

    # Exit code
    if total_failed > 0:
        print(f"\n❌ {total_failed} test(s) failed!")
        sys.exit(1)
    else:
        print(f"\n✅ All {total_passed} tests passed!")
        sys.exit(0)


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="E2E Acceptance Test Runner for Syn137 (Features F8-F12)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--feature",
        choices=["F8", "F9", "F10", "F11", "F12", "all"],
        default="all",
        help="Run tests for a specific feature (default: all)",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Run live agent tests (requires ANTHROPIC_API_KEY)",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show detailed test output",
    )

    args = parser.parse_args()

    print_header("Syn137 E2E ACCEPTANCE TESTS (F8-F12)")
    print(f"\n  Date: {datetime.now(UTC).isoformat()}")
    print(f"  Feature: {args.feature}")
    print(f"  Live tests: {'Yes' if args.live else 'No'}")
    print(f"  Verbose: {'Yes' if args.verbose else 'No'}")

    results: list[FeatureResult] = []

    if args.feature in ("F8", "all"):
        results.append(test_f8_agentic_execution(args.verbose, args.live))

    if args.feature in ("F9", "all"):
        results.append(test_f9_workspace_hooks(args.verbose))

    if args.feature in ("F10", "all"):
        results.append(test_f10_artifacts(args.verbose))

    if args.feature in ("F11", "all"):
        results.append(test_f11_event_bridge(args.verbose))

    if args.feature in ("F12", "all"):
        results.append(test_f12_providers(args.verbose))

    print_summary(results)


if __name__ == "__main__":
    main()
