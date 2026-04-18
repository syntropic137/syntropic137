"""Base class for test-only in-memory adapters.

All in-memory adapters that must NOT run in production inherit from
InMemoryAdapter. The environment check runs once at instantiation.

See ADR-060 (docs/adrs/ADR-060-restart-safe-trigger-deduplication.md)
for why in-memory state is dangerous in production (restart storms).
"""

from __future__ import annotations

from syn_shared.settings import get_settings


class InMemoryAdapterError(Exception):
    """Raised when an in-memory adapter is used outside test/offline."""


def assert_test_only() -> None:
    """Assert that the current environment allows in-memory adapters.

    Call this directly when inheritance from InMemoryAdapter is not
    possible (e.g., dataclasses). InMemoryAdapter.__init__ calls this
    internally, so subclasses get the check automatically.

    Raises:
        InMemoryAdapterError: If not in test or offline environment.
    """
    settings = get_settings()
    if not settings.uses_in_memory_stores:
        raise InMemoryAdapterError(
            "In-memory adapters are test/offline only. "
            f"Current environment: {settings.app_environment}. "
            "Configure a durable backend for production use."
        )


class InMemoryAdapter:
    """Base for test-only in-memory adapters.

    Raises InMemoryAdapterError if instantiated in production.
    Uses ``settings.uses_in_memory_stores`` (= is_test or is_offline),
    the single canonical check for the entire codebase.

    See ADR-060 (docs/adrs/ADR-060-restart-safe-trigger-deduplication.md).
    """

    def __init__(self) -> None:
        assert_test_only()
