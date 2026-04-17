"""Tests for PendingSHAStore durability guarantees.

PendingSHAStore must NOT fall back to in-memory in production.
The Postgres implementation already exists -- the in-memory fallback
was a shortcut that violates ADR-060's restart safety guarantees.
"""

from __future__ import annotations


class TestPendingSHADurability:
    """PendingSHAStore must be durable in production environments."""

    def test_in_memory_pending_sha_store_inherits_guard(self) -> None:
        """InMemoryPendingSHAStore must inherit InMemoryAdapter (production guard).

        Before fix: InMemoryPendingSHAStore did NOT inherit InMemoryAdapter,
        allowing it to run in production where it loses data on restart.
        After fix: inherits InMemoryAdapter, raises InMemoryAdapterError in prod.
        """
        from syn_adapters.github.pending_sha_store import InMemoryPendingSHAStore
        from syn_adapters.in_memory import InMemoryAdapter

        assert issubclass(InMemoryPendingSHAStore, InMemoryAdapter), (
            "InMemoryPendingSHAStore must inherit from InMemoryAdapter "
            "to prevent accidental use in production. "
            "See ADR-060: all in-memory adapters must be test-only."
        )
