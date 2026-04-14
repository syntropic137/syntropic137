"""Fitness function: in-memory state classification audit.

Every in-memory data structure used for correctness or safety
(asyncio.Lock dicts, rate-limit counters, pending-task maps) must
carry a classification comment so reviewers understand the restart
and multi-instance implications:

  # CORRECTNESS: requires distributed lock for multi-instance (E1)
  # ACKNOWLEDGED: triggers deferred on restart, acceptable for debounce use case
  # PERFORMANCE: tracking resets on restart, acceptable for rate limiting

This test enforces that known in-memory state locations carry one of
these classification markers.
"""

from __future__ import annotations

import pytest
from ci.fitness.conftest import repo_root

_CLASSIFICATION_MARKERS = (
    "# CORRECTNESS:",
    "# ACKNOWLEDGED:",
    "# PERFORMANCE:",
)

# Known in-memory state locations: (relative path, variable pattern, description)
_KNOWN_STATE: list[tuple[str, str, str]] = [
    (
        "packages/syn-domain/src/syn_domain/contexts/github/slices/evaluate_webhook/EvaluateWebhookHandler.py",
        "_fire_locks",
        "per-(trigger, pr) asyncio.Lock dict for concurrency guard",
    ),
    (
        "packages/syn-domain/src/syn_domain/contexts/github/slices/evaluate_webhook/debouncer.py",
        "_pending",
        "pending debounce task dict",
    ),
    (
        "packages/syn-domain/src/syn_domain/contexts/github/slices/evaluate_webhook/safety_guards.py",
        "_dispatch_timestamps",
        "dispatch rate limit timestamp list",
    ),
    (
        "apps/syn-api/src/syn_api/routes/webhooks/signature.py",
        "_sig_failures",
        "signature failure rate limiter dict",
    ),
]


def _has_classification(content: str, variable: str) -> bool:
    """Check if the variable declaration has a classification comment nearby.

    Looks for a classification marker in the 3 lines preceding the FIRST
    occurrence of the variable (its declaration), which avoids false positives
    from later usages that happen to sit near an unrelated comment.
    """
    lines = content.splitlines()
    for i, line in enumerate(lines):
        if variable in line:
            # Only check the first occurrence (the declaration)
            window = lines[max(0, i - 3) : i + 1]
            for window_line in window:
                if any(marker in window_line for marker in _CLASSIFICATION_MARKERS):
                    return True
            # First occurrence checked - stop scanning
            return False
    return False


@pytest.mark.architecture
class TestInMemoryStateAudit:
    def test_known_in_memory_state_is_classified(self) -> None:
        """Every known in-memory correctness mechanism must have a classification comment."""
        root = repo_root()
        missing: list[str] = []

        for rel_path, variable, description in _KNOWN_STATE:
            filepath = root / rel_path
            if not filepath.exists():
                missing.append(f"{rel_path}: file not found (expected {variable})")
                continue

            content = filepath.read_text(encoding="utf-8")

            if variable not in content:
                missing.append(f"{rel_path}: variable '{variable}' not found")
                continue

            if not _has_classification(content, variable):
                missing.append(
                    f"{rel_path}: '{variable}' ({description}) lacks a "
                    f"classification comment (CORRECTNESS/ACKNOWLEDGED/PERFORMANCE)"
                )

        if missing:
            joined = "\n  ".join(missing)
            pytest.fail(
                f"Found {len(missing)} in-memory state location(s) without classification:\n"
                f"  {joined}\n\n"
                "Add a comment above or on the same line as the declaration:\n"
                "  # CORRECTNESS: <why this needs distributed state for multi-instance>\n"
                "  # ACKNOWLEDGED: <why ephemeral state is acceptable>\n"
                "  # PERFORMANCE: <why reset-on-restart is OK>"
            )

    def test_registry_completeness(self) -> None:
        """Sanity check: the known-state registry references real files."""
        root = repo_root()
        for rel_path, variable, _desc in _KNOWN_STATE:
            filepath = root / rel_path
            assert filepath.exists(), f"Registry entry references missing file: {rel_path}"
            content = filepath.read_text(encoding="utf-8")
            assert variable in content, (
                f"Registry entry references missing variable '{variable}' in {rel_path}"
            )
