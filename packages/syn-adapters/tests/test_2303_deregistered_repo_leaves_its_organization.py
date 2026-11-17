"""#2303: a deregistered repo stops counting toward its organization.

``organization_list`` was not subscribed to ``RepoDeregistered``, and its
decrement handler had no ``on_repo_deregistered`` name for the coordinator to
find, so ``GET /organizations`` and ``GET /organizations/{id}`` kept counting
every repo ever registered.

Events come from ``RepoAggregate`` itself and go through ``as_checkpointed``
and ``deliver``, the coordinator's subscription and dispatch, so the test
fails when either the subscription or the handler name is lost. Each
assertion reads ``repo_count`` from both reads the API routes make.
"""

from __future__ import annotations

import os

os.environ.setdefault("APP_ENVIRONMENT", "test")

import pytest
from event_sourcing import EventEnvelope, EventMetadata

from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore
from syn_adapters.subscriptions.read_model_dispatch import as_checkpointed, deliver
from syn_domain.contexts.organization._shared.organization_projection import (
    OrganizationProjection,
)
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
from syn_domain.contexts.organization.domain.events.OrganizationCreatedEvent import (
    OrganizationCreatedEvent,
)


class _Orgs:
    """The organization read model, fed the way the coordinator feeds it."""

    def __init__(self) -> None:
        self.orgs = OrganizationProjection(InMemoryProjectionStore())
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
        adapter = as_checkpointed(self.orgs)
        assert adapter is not None
        await deliver([adapter], stamped)

    async def create(self, org_id: str) -> None:
        await self._deliver(
            EventEnvelope(
                event=OrganizationCreatedEvent(organization_id=org_id, name=org_id, slug=org_id),
                metadata=EventMetadata(
                    aggregate_id=org_id, aggregate_type="Organization", aggregate_nonce=1
                ),
            )
        )

    async def publish(self, repo: RepoAggregate) -> None:
        """Deliver what the aggregate just decided, as the event store would."""
        for envelope in repo.get_uncommitted_events():
            await self._deliver(envelope)
        repo.mark_events_as_committed()

    async def register(self, org_id: str, repo_id: str) -> RepoAggregate:
        repo = RepoAggregate()
        repo.register(
            RegisterRepoCommand(
                organization_id=org_id, full_name=f"acme/{repo_id}", aggregate_id=repo_id
            )
        )
        await self.publish(repo)
        return repo

    async def deregister(self, repo: RepoAggregate, repo_id: str) -> None:
        repo.deregister(DeregisterRepoCommand(repo_id=repo_id))
        await self.publish(repo)

    async def repo_count(self, org_id: str) -> int:
        """repo_count as the show route reads it, checked against the list route."""
        org = await self.orgs.get(org_id)
        assert org is not None
        listed = {o.organization_id: o.repo_count for o in await self.orgs.list_all()}
        assert listed[org_id] == org.repo_count
        return org.repo_count


@pytest.mark.unit
@pytest.mark.asyncio
async def test_deregistering_a_repo_removes_it_from_its_organization_count() -> None:
    orgs = _Orgs()
    await orgs.create("org-1")
    await orgs.create("org-2")
    kept = await orgs.register("org-1", "repo-kept")
    gone = await orgs.register("org-1", "repo-gone")
    await orgs.register("org-2", "repo-other")
    assert (await orgs.repo_count("org-1"), await orgs.repo_count("org-2")) == (2, 1)

    await orgs.deregister(gone, "repo-gone")

    assert (await orgs.repo_count("org-1"), await orgs.repo_count("org-2")) == (1, 1)
    await orgs.deregister(kept, "repo-kept")
    assert (await orgs.repo_count("org-1"), await orgs.repo_count("org-2")) == (0, 1)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_deregister_after_assign_and_unassign_decrements_the_organization_once() -> None:
    orgs = _Orgs()
    await orgs.create("org-1")
    await orgs.create("org-2")
    repo = await orgs.register("org-1", "repo-1")
    await orgs.register("org-1", "repo-2")
    await orgs.register("org-2", "repo-other")
    repo.assign_to_system(AssignRepoToSystemCommand(repo_id="repo-1", system_id="sys-a"))
    await orgs.publish(repo)
    repo.unassign_from_system(UnassignRepoFromSystemCommand(repo_id="repo-1"))
    await orgs.publish(repo)
    assert (await orgs.repo_count("org-1"), await orgs.repo_count("org-2")) == (2, 1)

    await orgs.deregister(repo, "repo-1")

    assert (await orgs.repo_count("org-1"), await orgs.repo_count("org-2")) == (1, 1)
