"""Workflow tags on the read side (#967).

#959: asserted on FRESH projections replaying what a real repository wrote,
through ``handle_event``, the coordinator's entry point. The detail model is
covered beside the list because the export is built from it: a tag missing
there is a tag the YAML round trip silently loses.
"""

from __future__ import annotations

import os

os.environ.setdefault("APP_ENVIRONMENT", "test")

import pytest
from event_sourcing import EventStoreRepository
from event_sourcing.client.memory import MemoryEventStoreClient
from event_sourcing.stores.memory_checkpoint import MemoryCheckpointStore

from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore
from syn_adapters.storage.repositories import RepositoryAdapter
from syn_domain.contexts.orchestration._shared.tags import TagSet
from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.value_objects import (
    PhaseDefinition,
    WorkflowClassification,
    WorkflowType,
)
from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.WorkflowTemplateAggregate import (
    WorkflowTemplateAggregate,
)
from syn_domain.contexts.orchestration.domain.commands.AddWorkflowTagsCommand import (
    AddWorkflowTagsCommand,
)
from syn_domain.contexts.orchestration.domain.commands.CreateWorkflowTemplateCommand import (
    CreateWorkflowTemplateCommand,
)
from syn_domain.contexts.orchestration.domain.commands.RemoveWorkflowTagsCommand import (
    RemoveWorkflowTagsCommand,
)
from syn_domain.contexts.orchestration.domain.commands.UpdateWorkflowTemplateCommand import (
    UpdateWorkflowTemplateCommand,
)
from syn_domain.contexts.orchestration.slices.get_workflow_detail.projection import (
    WorkflowDetailProjection,
)
from syn_domain.contexts.orchestration.slices.list_workflows.projection import (
    WorkflowListProjection,
)
from syn_domain.testing.stored_replay import replay

WORKFLOW_ID = "wf-tags"


def _create(tags: list[str]) -> CreateWorkflowTemplateCommand:
    return CreateWorkflowTemplateCommand(
        aggregate_id=WORKFLOW_ID,
        name="Tagged",
        workflow_type=WorkflowType.RESEARCH,
        classification=WorkflowClassification.SIMPLE,
        repository_url="",
        requires_repos=False,
        phases=[PhaseDefinition(phase_id="p1", name="P1", order=1)],
        tags=TagSet(tags),
    )


def _update(tags: list[str]) -> UpdateWorkflowTemplateCommand:
    """A reinstall, as CreateWorkflowTemplateHandler turns a forced create into one."""
    return UpdateWorkflowTemplateCommand(
        **_create(tags).model_dump(exclude={"force", "version", "source_digest"}),
        force=True,
    )


async def _replay(
    client: MemoryEventStoreClient,
) -> tuple[WorkflowListProjection, WorkflowDetailProjection]:
    listing = WorkflowListProjection(InMemoryProjectionStore())
    detail = WorkflowDetailProjection(InMemoryProjectionStore())
    await replay(client, MemoryCheckpointStore(), listing, detail)
    return listing, detail


def _repository(client: MemoryEventStoreClient) -> RepositoryAdapter[WorkflowTemplateAggregate]:
    return RepositoryAdapter(
        EventStoreRepository(
            client,
            WorkflowTemplateAggregate,  # type: ignore[arg-type]  # ESP SDK TEvent invariance
            "WorkflowTemplate",
        )
    )


async def _tags_on_both(client: MemoryEventStoreClient) -> tuple[tuple[str, ...], tuple[str, ...]]:
    listing, detail = await _replay(client)
    (summary,) = await listing.get_all()
    full = await detail.get_by_id(WORKFLOW_ID)
    assert full is not None
    return summary.tags, full.tags


@pytest.mark.unit
class TestReplayRebuildsWorkflowTags:
    async def test_created_then_edited_tags_replay(self) -> None:
        client = MemoryEventStoreClient()
        repository = _repository(client)
        aggregate = WorkflowTemplateAggregate()
        aggregate._handle_command(_create(["nightly", "smoke"]))  # pyright: ignore[reportPrivateUsage]
        await repository.save_new(aggregate)

        loaded = await repository.get_by_id(WORKFLOW_ID)
        assert loaded is not None
        loaded.add_tags(AddWorkflowTagsCommand(aggregate_id=WORKFLOW_ID, tags=TagSet(["release"])))
        loaded.remove_tags(
            RemoveWorkflowTagsCommand(aggregate_id=WORKFLOW_ID, tags=TagSet(["smoke"]))
        )
        await repository.save(loaded)

        assert await _tags_on_both(client) == (("nightly", "release"), ("nightly", "release"))

    async def test_a_reinstall_replaces_the_tags(self) -> None:
        client = MemoryEventStoreClient()
        repository = _repository(client)
        aggregate = WorkflowTemplateAggregate()
        aggregate._handle_command(_create(["old"]))  # pyright: ignore[reportPrivateUsage]
        await repository.save_new(aggregate)

        loaded = await repository.get_by_id(WORKFLOW_ID)
        assert loaded is not None
        loaded._handle_command(_update(["new"]))  # pyright: ignore[reportPrivateUsage]
        await repository.save(loaded)

        assert await _tags_on_both(client) == (("new",), ("new",))
