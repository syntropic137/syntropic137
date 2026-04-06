"""In-memory repository for RepoClaim aggregates (TESTING ONLY).

Supports save_new() semantics for stream-per-unique-value pattern.

WARNING: This repository is for unit/integration tests only.
"""

from __future__ import annotations

from typing import Any

from event_sourcing import StreamAlreadyExistsError

from syn_adapters.storage.in_memory import _assert_test_environment


class InMemoryRepoClaimRepository:
    """In-memory repository for RepoClaim aggregates.

    Used for testing ONLY. Supports save_new() for atomic claim creation.

    Raises:
        InMemoryStorageError: If instantiated outside test environment.
    """

    def __init__(self) -> None:
        _assert_test_environment()
        self._claims: dict[str, Any] = {}

    async def save(self, aggregate: Any) -> None:  # noqa: ANN401
        """Save the claim aggregate and publish uncommitted events."""
        if aggregate.id:
            self._claims[str(aggregate.id)] = aggregate
        events = (
            aggregate.get_uncommitted_events()
            if hasattr(aggregate, "get_uncommitted_events")
            else []
        )
        if events:
            from syn_adapters.storage.in_memory_factories import get_event_publisher

            publisher = get_event_publisher()
            await publisher.publish(events)

    async def save_new(self, aggregate: Any) -> None:  # noqa: ANN401
        """Save a new claim (raises StreamAlreadyExistsError if claim exists and is active)."""
        claim_id = str(aggregate.id) if aggregate.id else ""
        if claim_id and claim_id in self._claims:
            existing = self._claims[claim_id]
            if not (hasattr(existing, "is_released") and existing.is_released):
                raise StreamAlreadyExistsError(
                    stream_name=f"RepoClaim-{claim_id}",
                    actual_version=1,
                )
        await self.save(aggregate)

    async def get_by_id(self, claim_id: str) -> Any:  # noqa: ANN401
        """Get claim by ID."""
        return self._claims.get(claim_id)

    async def exists(self, claim_id: str) -> bool:
        """Check if claim exists."""
        return claim_id in self._claims

    def clear(self) -> None:
        """Clear all claims."""
        self._claims = {}
