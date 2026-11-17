"""#2300: a deregistered repo stops counting toward the system it was in.

``RepoDeregistered`` reached neither ``system_list`` nor ``repo_list``, so a
repo deregistered while assigned stayed in ``GET /systems/{id}`` repo_count,
in ``GET /systems/{id}/status`` and in the repo list filtered by system.

Events come from ``RepoAggregate`` itself and go through ``as_checkpointed``
and ``deliver``, the coordinator's subscription and dispatch, so the test
fails when the subscription or the handler name is lost, not only when a
handler is wrong. Each assertion reads the value the API route reads.
"""

from __future__ import annotations

import os

os.environ.setdefault("APP_ENVIRONMENT", "test")

import pytest
from event_sourcing import EventEnvelope, EventMetadata

from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore
from syn_adapters.subscriptions.read_model_dispatch import as_checkpointed, deliver
from syn_domain.contexts.organization.domain.aggregate_repo.RepoAggregate import RepoAggregate
from syn_domain.contexts.organization.domain.commands.AssignRepoToSystemCommand import (
    AssignRepoToSystemCommand,
)
from syn_domain.contexts.organization.domain.commands.DeregisterRepoCommand import (
    DeregisterRepoCommand,
)
from syn_domain.contexts.organization.domain.commands.RegisterRepoCommand import (
    RegisterRepoCommand,
)
from syn_domain.contexts.organization.domain.commands.UnassignRepoFromSystemCommand import (
    UnassignRepoFromSystemCommand,
)
from syn_domain.contexts.organization.domain.events.SystemCreatedEvent import SystemCreatedEvent
from syn_domain.contexts.organization.domain.queries.get_system_status import (
    GetSystemStatusQuery,
)
from syn_domain.contexts.organization.slices.list_repos.projection import RepoProjection
from syn_domain.contexts.organization.slices.list_systems.projection import SystemProjection
from syn_domain.contexts.organization.slices.system_status.GetSystemStatusHandler import (
    GetSystemStatusHandler,
)


class _Org:
    """The system and repo read models, fed the way the coordinator feeds them."""

    def __init__(self) -> None:
        self.store = InMemoryProjectionStore()
        self.systems = SystemProjection(self.store)
        self.repos = RepoProjection(self.store)
        self._nonce = 0

    async def _deliver(self, envelope: EventEnvelope) -> None:
        self._nonce += 1
        stamped = envelope.model_copy(
            update={
                "metadata": envelope.metadata.model_copy(
                    update={
                        "event_type": type(envelope.event).event_type,  # type: ignore[attr-defined]
                        "global_nonce": self._nonce,
                    }
                )
            }
        )
        adapters = [as_checkpointed(self.systems), as_checkpointed(self.repos)]
        await deliver([a for a in adapters if a is not None], stamped)

    async def create_system(self, system_id: str) -> None:
        await self._deliver(
            EventEnvelope(
                event=SystemCreatedEvent(
                    system_id=system_id, organization_id="org-1", name=system_id
                ),
                metadata=EventMetadata(
                    aggregate_id=system_id, aggregate_type="System", aggregate_nonce=1
                ),
            )
        )

    async def publish(self, repo: RepoAggregate) -> None:
        """Deliver what the aggregate just decided, as the event store would."""
        for envelope in repo.get_uncommitted_events():
            await self._deliver(envelope)
        repo.mark_events_as_committed()

    async def register(self, repo_id: str) -> RepoAggregate:
        repo = RepoAggregate()
        repo.register(
            RegisterRepoCommand(
                organization_id="org-1", full_name=f"acme/{repo_id}", aggregate_id=repo_id
            )
        )
        await self.publish(repo)
        return repo

    async def counts(self, system_id: str) -> tuple[int, int, int]:
        """(show repo_count, status total_repos, listed) for one system."""
        system = await self.systems.get(system_id)
        assert system is not None
        status = await GetSystemStatusHandler(self.store, self.systems, self.repos).handle(
            GetSystemStatusQuery(system_id=system_id)
        )
        assert status.total_repos == len(status.repos)
        listed = await self.repos.list_all(system_id=system_id)
        return system.repo_count, status.total_repos, len(listed)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_deregistering_an_assigned_repo_removes_it_from_show_status_and_list() -> None:
    org = _Org()
    await org.create_system("sys-a")
    repo = await org.register("repo-1")
    repo.assign_to_system(AssignRepoToSystemCommand(repo_id="repo-1", system_id="sys-a"))
    await org.publish(repo)
    assert await org.counts("sys-a") == (1, 1, 1)

    repo.deregister(DeregisterRepoCommand(repo_id="repo-1"))
    await org.publish(repo)

    assert await org.counts("sys-a") == (0, 0, 0)
    # The unfiltered list hides it too: list_all's default and the event's contract.
    assert [r.repo_id for r in await org.repos.list_all()] == []
    hidden = await org.repos.list_all(include_deregistered=True)
    assert [(r.repo_id, r.is_deregistered) for r in hidden] == [("repo-1", True)]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_deregistering_an_unassigned_repo_moves_no_system_count() -> None:
    org = _Org()
    await org.create_system("sys-a")
    kept = await org.register("repo-kept")
    kept.assign_to_system(AssignRepoToSystemCommand(repo_id="repo-kept", system_id="sys-a"))
    await org.publish(kept)
    loose = await org.register("repo-loose")

    loose.deregister(DeregisterRepoCommand(repo_id="repo-loose"))
    await org.publish(loose)

    assert await org.counts("sys-a") == (1, 1, 1)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_deregister_after_reassign_leaves_only_the_current_system() -> None:
    org = _Org()
    await org.create_system("sys-a")
    await org.create_system("sys-b")
    repo = await org.register("repo-1")
    other = await org.register("repo-2")
    other.assign_to_system(AssignRepoToSystemCommand(repo_id="repo-2", system_id="sys-a"))
    await org.publish(other)
    repo.assign_to_system(AssignRepoToSystemCommand(repo_id="repo-1", system_id="sys-a"))
    await org.publish(repo)
    repo.unassign_from_system(UnassignRepoFromSystemCommand(repo_id="repo-1"))
    await org.publish(repo)
    repo.assign_to_system(AssignRepoToSystemCommand(repo_id="repo-1", system_id="sys-b"))
    await org.publish(repo)
    assert await org.counts("sys-a") == (1, 1, 1)
    assert await org.counts("sys-b") == (1, 1, 1)

    repo.deregister(DeregisterRepoCommand(repo_id="repo-1"))
    await org.publish(repo)

    assert await org.counts("sys-a") == (1, 1, 1)
    assert await org.counts("sys-b") == (0, 0, 0)
