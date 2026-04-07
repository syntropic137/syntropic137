"""Generic repository protocol for domain handlers.

Defines the interface that all aggregate repositories expose to domain
handlers.  The adapter layer (``RepositoryAdapter`` in syn-adapters)
implements this protocol by wrapping the ESP SDK's
``EventStoreRepository``.

This is a domain-level port -- handlers depend on this protocol, not on
concrete infrastructure types.
"""

from __future__ import annotations

from typing import Protocol, TypeVar

TAggregate = TypeVar("TAggregate")


class Repository(Protocol[TAggregate]):
    """Repository protocol for aggregate persistence.

    Mirrors the public surface of ``RepositoryAdapter[TAggregate]`` so that
    domain handlers can accept any implementation (production adapter,
    in-memory test double, etc.) via structural sub-typing.
    """

    async def get_by_id(self, aggregate_id: str) -> TAggregate | None:
        """Load an aggregate by its unique identifier."""
        ...

    async def save(self, aggregate: TAggregate) -> None:
        """Persist uncommitted events for an aggregate."""
        ...

    async def save_new(self, aggregate: TAggregate) -> None:
        """Persist a brand-new aggregate (raises on duplicate stream)."""
        ...

    async def exists(self, aggregate_id: str) -> bool:
        """Check whether an aggregate stream exists."""
        ...
