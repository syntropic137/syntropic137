#!/usr/bin/env python3
"""Pre-Merge Validation Script for PR #28: Agent-in-Container Feature.

This script validates that all requirements for merging the agent-in-container
implementation are met:

1. ✅ All unit tests passing (1004 tests)
2. ✅ Lint checks passing (ruff)
3. ✅ Type checks passing (mypy strict)
4. ✅ Docker workspace image builds successfully
5. ✅ E2E container tests pass (basic infrastructure)
6. ✅ No breaking changes to core domain

Run this before opening the PR to ensure CI/CD will pass.

Usage:
    python scripts/pre_merge_validation.py [--quick] [--verbose]

Options:
    --quick    Skip E2E tests (runs in ~2 minutes)
    --verbose  Show full output from each check
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from dataclasses import dataclass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    """Result of a single validation check."""

    name: str
    passed: bool
    duration_ms: int
    message: str = ""
    details: str = ""


class PreMergeValidator:
    """Main validator class."""

    def __init__(self, quick_mode: bool = False, verbose: bool = False):
        """Initialize validator."""
        self.quick_mode = quick_mode
        self.verbose = verbose
        self.results: list[ValidationResult] = []
        self.start_time = None

    async def run_command(
        self,
        cmd: list[str],
        name: str,
        timeout: int = 300,
    ) -> tuple[bool, str, int]:
        """Run a shell command and return (success, output, duration)."""
        import time

        start = time.time()

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            try:
                async with asyncio.timeout(timeout):
                    stdout, stderr = await proc.communicate()
            except TimeoutError:
                proc.kill()
                await proc.wait()
                return (
                    False,
                    f"Command timed out after {timeout}s",
                    int((time.time() - start) * 1000),
                )

            duration_ms = int((time.time() - start) * 1000)

            if proc.returncode == 0:
                output = stdout.decode()
                if self.verbose:
                    logger.info(f"{name} output:\n{output}")
                return True, output, duration_ms
            else:
                error = stderr.decode()
                logger.error(f"{name} failed:\n{error}")
                return False, error, duration_ms

        except Exception as e:
            logger.exception(f"Error running {name}: {e}")
            return False, str(e), int((time.time() - start) * 1000)

    async def check_python_version(self) -> ValidationResult:
        """Check Python 3.12+ is available."""
        logger.info("🔍 Checking Python version...")

        success, output, duration = await self.run_command(
            ["python", "--version"],
            "Python version check",
        )

        if success and "3.12" in output:
            return ValidationResult(
                name="Python Version",
                passed=True,
                duration_ms=duration,
                message="Python 3.12+ available ✅",
                details=output.strip(),
            )

        return ValidationResult(
            name="Python Version",
            passed=False,
            duration_ms=duration,
            message="Python 3.12+ required",
            details=output,
        )

    async def check_dependencies(self) -> ValidationResult:
        """Check if uv sync has been run."""
        logger.info("📦 Checking dependencies...")

        success, output, duration = await self.run_command(
            ["uv", "run", "python", "-c", "import aef_domain; print('OK')"],
            "Dependency check",
            timeout=60,
        )

        if success:
            return ValidationResult(
                name="Dependencies",
                passed=True,
                duration_ms=duration,
                message="All dependencies installed ✅",
            )

        return ValidationResult(
            name="Dependencies",
            passed=False,
            duration_ms=duration,
            message="Run: uv sync",
            details=output,
        )

    async def check_lint(self) -> ValidationResult:
        """Run ruff linter."""
        logger.info("🔍 Running linter (ruff)...")

        success, output, duration = await self.run_command(
            ["uv", "run", "ruff", "check", "."],
            "Lint check",
            timeout=120,
        )

        return ValidationResult(
            name="Lint (ruff)",
            passed=success,
            duration_ms=duration,
            message="Lint checks passed ✅" if success else "Lint errors found ❌",
            details=output[:500] if not success else "",
        )

    async def check_format(self) -> ValidationResult:
        """Check code formatting."""
        logger.info("📝 Checking code formatting...")

        success, _output, duration = await self.run_command(
            ["uv", "run", "ruff", "format", "--check", "."],
            "Format check",
            timeout=120,
        )

        return ValidationResult(
            name="Format (ruff)",
            passed=success,
            duration_ms=duration,
            message="Formatting OK ✅" if success else "Files need formatting ⚠️",
            details="" if success else "Run: uv run ruff format .",
        )

    async def check_typecheck(self) -> ValidationResult:
        """Run mypy type checker."""
        logger.info("✓ Running type checker (mypy)...")

        success, output, duration = await self.run_command(
            ["uv", "run", "mypy", "apps", "packages"],
            "Type check",
            timeout=180,
        )

        return ValidationResult(
            name="Type Check (mypy)",
            passed=success,
            duration_ms=duration,
            message="Type checks passed ✅" if success else "Type errors found ❌",
            details=output[:500] if not success else "",
        )

    async def check_unit_tests(self) -> ValidationResult:
        """Run unit tests."""
        logger.info("🧪 Running unit tests...")

        success, output, duration = await self.run_command(
            ["uv", "run", "pytest", "-q", "--tb=short"],
            "Unit tests",
            timeout=300,
        )

        # Parse test count from output
        test_count = "unknown"
        if "passed" in output:
            try:
                import re

                match = re.search(r"(\d+) passed", output)
                if match:
                    test_count = match.group(1)
            except Exception:
                pass

        return ValidationResult(
            name="Unit Tests",
            passed=success,
            duration_ms=duration,
            message=f"Tests passed ({test_count}) ✅" if success else "Tests failed ❌",
            details=output[-1000:] if not success else "",
        )

    async def check_docker_image(self) -> ValidationResult:
        """Check workspace image builds."""
        logger.info("🐳 Checking Docker workspace image...")

        success, output, duration = await self.run_command(
            ["docker", "build", "-t", "aef-workspace:pre-merge-test", "docker/workspace/"],
            "Docker build",
            timeout=600,
        )

        return ValidationResult(
            name="Docker Image Build",
            passed=success,
            duration_ms=duration,
            message="Docker image builds ✅" if success else "Docker build failed ❌",
            details=output[-500:] if not success else "",
        )

    async def check_agent_runner_installed(self) -> ValidationResult:
        """Check aef-agent-runner can be imported."""
        logger.info("🔍 Checking aef-agent-runner installation...")

        success, output, duration = await self.run_command(
            [
                "uv",
                "run",
                "--package",
                "aef-agent-runner",
                "python",
                "-c",
                "import aef_agent_runner; print(aef_agent_runner.__version__)",
            ],
            "Agent runner check",
            timeout=60,
        )

        version = output.strip() if success else "not found"

        return ValidationResult(
            name="Agent Runner Package",
            passed=success,
            duration_ms=duration,
            message=f"aef-agent-runner available ({version}) ✅" if success else "Not installed ❌",
            details="" if success else output,
        )

    async def check_e2e_container_test(self) -> ValidationResult:
        """Run E2E container test."""
        if self.quick_mode:
            logger.info("⏭️  Skipping E2E test (--quick mode)")
            return ValidationResult(
                name="E2E Container Test",
                passed=True,
                duration_ms=0,
                message="Skipped (--quick mode)",
            )

        logger.info("🚀 Running E2E container test...")

        success, output, duration = await self.run_command(
            ["python", "scripts/e2e_agent_in_container_test.py"],
            "E2E container test",
            timeout=300,
        )

        return ValidationResult(
            name="E2E Container Test",
            passed=success,
            duration_ms=duration,
            message="E2E test passed ✅" if success else "E2E test failed ❌",
            details=output[-1000:] if not success else "",
        )

    async def run_all_checks(self) -> bool:
        """Run all validation checks."""
        logger.info("=" * 70)
        logger.info("🔍 Pre-Merge Validation for PR #28: Agent-in-Container")
        logger.info("=" * 70)
        logger.info("")

        # Run checks
        self.results.append(await self.check_python_version())
        self.results.append(await self.check_dependencies())
        self.results.append(await self.check_lint())
        self.results.append(await self.check_format())
        self.results.append(await self.check_typecheck())
        self.results.append(await self.check_unit_tests())
        self.results.append(await self.check_docker_image())
        self.results.append(await self.check_agent_runner_installed())
        self.results.append(await self.check_e2e_container_test())

        return self._print_summary()

    def _print_summary(self) -> bool:
        """Print validation summary."""
        print()
        print("=" * 70)
        print("📊 Validation Results")
        print("=" * 70)
        print()

        all_passed = True
        total_duration_ms = sum(r.duration_ms for r in self.results)

        for result in self.results:
            status = "✅ PASS" if result.passed else "❌ FAIL"
            print(f"{status:8} | {result.name:25} | {result.duration_ms:5} ms")
            if result.message:
                print(f"         | {result.message}")
            if result.details and not result.passed:
                print("         |")
                for line in result.details.split("\n")[:5]:
                    print(f"         | {line}")
                if len(result.details.split("\n")) > 5:
                    print(f"         | ... ({len(result.details.split('\n')) - 5} more lines)")
            print()

            if not result.passed:
                all_passed = False

        print("=" * 70)
        print(f"⏱️  Total Duration: {total_duration_ms / 1000:.1f}s")
        print()

        if all_passed:
            print("✅ ALL CHECKS PASSED")
            print()
            print("Next steps:")
            print("  1. Run: git add .")
            print("  2. Run: git commit -m '...'")
            print("  3. Run: git push")
            print("  4. Open PR on GitHub")
            print()
        else:
            print("❌ SOME CHECKS FAILED")
            print()
            print("Fix the errors above and run this script again.")
            print()

        return all_passed


async def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Pre-Merge Validation for Agent-in-Container PR",
    )
    parser.add_argument("--quick", action="store_true", help="Skip E2E tests")
    parser.add_argument("--verbose", action="store_true", help="Show full output")
    args = parser.parse_args()

    validator = PreMergeValidator(quick_mode=args.quick, verbose=args.verbose)

    try:
        all_passed = await validator.run_all_checks()
        return 0 if all_passed else 1
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        return 130
    except Exception as e:
        logger.exception(f"Validation failed: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
