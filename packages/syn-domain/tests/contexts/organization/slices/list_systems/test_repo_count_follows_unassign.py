"""A system's repo_count goes back down when a repo is unassigned.

Release rehearsal 2026-10-10: assign then unassign left the count at 1.
The projection read ``old_system_id`` while RepoUnassignedFromSystemEvent
carries ``previous_system_id``.
"""

from __future__ import annotations

import pytest

from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore
from syn_domain.contexts.organization.domain.events.RepoUnassignedFromSystemEvent import (
    RepoUnassignedFromSystemEvent,
)
from syn_domain.contexts.organization.slices.list_systems.projection import (
    PROJECTION_NAME,
    SystemProjection,
)

pytestmark = pytest.mark.unit


async def test_unassign_decrements_the_system_it_left() -> None:
    store = InMemoryProjectionStore()
    projection = SystemProjection(store)
    await store.save(PROJECTION_NAME, "sys-1", {"system_id": "sys-1", "repo_count": 0})

    await projection.on_repo_assigned_increment({"system_id": "sys-1", "repo_id": "repo-1"})
    assert (await store.get(PROJECTION_NAME, "sys-1"))["repo_count"] == 1

    # The dict the coordinator hands the handler has the event's own field names.
    event = RepoUnassignedFromSystemEvent(repo_id="repo-1", previous_system_id="sys-1")
    payload = event.model_dump(mode="json")
    assert "previous_system_id" in payload and "old_system_id" not in payload
    await projection.on_repo_unassigned_decrement(payload)

    assert (await store.get(PROJECTION_NAME, "sys-1"))["repo_count"] == 0
