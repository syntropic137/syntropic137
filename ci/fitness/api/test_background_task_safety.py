"""Fitness function: background task error handling safety.

Ensures every FastAPI BackgroundTasks.add_task() call has co-located
error handling. BackgroundTasks silently swallow exceptions — without
explicit error checking, failures are invisible.

See AGENTS.md § "Background Task Error Handling" for the required pattern.

The required pattern for any background task closure wrapping a Result-
returning function:

    async def _run() -> None:
        result = await some_service(...)
        if isinstance(result, Err):
            logger.error("Execution failed: %s", result.message)

Reference: issue #497 — workflow execution errors were invisible because
the background task closure discarded the Result return value.

Standard: ADR-062 (docs/adrs/ADR-062-architectural-fitness-function-standard.md)
"""

from __future__ import annotations

from pathlib import Path

import pytest


def _repo_root() -> Path:
    # ci/fitness/api/test_background_task_safety.py -> repo root is 3 levels up
    return Path(__file__).resolve().parents[3]


_ERROR_HANDLING_PATTERNS = [
    "isinstance(result",  # e.g. isinstance(result, Err)
    "logger.error",
    "logger.exception",
]

_GUIDANCE = (
    "BackgroundTasks.add_task() silently swallows exceptions. "
    "Every file using add_task() must co-locate explicit error handling.\n"
    "Required pattern:\n"
    "    async def _run() -> None:\n"
    "        result = await some_service(...)\n"
    "        if isinstance(result, Err):\n"
    '            logger.error("Task failed: %s", result.message)\n'
    "\n"
    "See AGENTS.md § 'Background Task Error Handling' for the canonical pattern."
)


@pytest.mark.architecture
class TestBackgroundTaskSafety:
    def test_all_background_tasks_have_error_handling(self) -> None:
        """Every file with add_task() must contain co-located error handling.

        Scans all Python files under apps/syn-api/src/ for add_task( calls.
        For each file found, verifies that the same file also contains at
        least one error-handling pattern: isinstance check (for Result/Err),
        logger.error, or logger.exception.
        """
        api_src = _repo_root() / "apps" / "syn-api" / "src"

        files_with_add_task: list[Path] = []
        for py_file in sorted(api_src.rglob("*.py")):
            if py_file.name.startswith("test_") or py_file.name in ("conftest.py", "__init__.py"):
                continue
            content = py_file.read_text(encoding="utf-8")
            if "add_task(" in content:
                files_with_add_task.append(py_file)

        if not files_with_add_task:
            pytest.skip("No add_task() calls found in apps/syn-api/src/ — nothing to check.")

        violations: list[str] = []
        for py_file in files_with_add_task:
            content = py_file.read_text(encoding="utf-8")
            has_error_handling = any(pattern in content for pattern in _ERROR_HANDLING_PATTERNS)
            if not has_error_handling:
                rel = py_file.relative_to(_repo_root())
                violations.append(str(rel))

        if violations:
            joined = "\n  ".join(violations)
            pytest.fail(
                f"Found {len(violations)} file(s) with add_task() but no error handling:\n"
                f"  {joined}\n\n"
                f"{_GUIDANCE}"
            )
