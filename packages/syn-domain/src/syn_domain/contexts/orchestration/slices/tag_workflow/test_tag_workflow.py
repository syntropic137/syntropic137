"""Tests for the tag-workflow slice (#967).

Driven through the real handlers, the real aggregate and a real event-store
repository; only the store itself is in memory. What is asserted is what a
fresh load of the stream replays, not what the handler said.
"""

from __future__ import annotations

import os

os.environ.setdefault("APP_ENVIRONMENT", "test")

import pytest
from event_sourcing import DomainEvent, EventEnvelope, EventStoreRepository
from event_sourcing.client.memory import MemoryEventStoreClient

from syn_adapters.storage.repositories import RepositoryAdapter
from syn_domain.contexts.orchestration._shared.tags import MAX_TAGS, TagSet
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
from syn_domain.contexts.orchestration.slices.tag_workflow import (
    AddWorkflowTagsHandler,
    RemoveWorkflowTagsHandler,
)

WORKFLOW_ID = "wf-tags"


class _Publisher:
    def __init__(self) -> None:
        self.event_types: list[str] = []

    async def publish(self, events: list[EventEnvelope[DomainEvent]]) -> None:
        self.event_types.extend(e.event.event_type for e in events)


def _repository() -> RepositoryAdapter[WorkflowTemplateAggregate]:
    return RepositoryAdapter(
        EventStoreRepository(
            MemoryEventStoreClient(),
            WorkflowTemplateAggregate,  # type: ignore[arg-type]  # ESP SDK TEvent invariance
            "WorkflowTemplate",
        )
    )


async def _workflow_with(
    repository: RepositoryAdapter[WorkflowTemplateAggregate], tags: list[str]
) -> None:
    aggregate = WorkflowTemplateAggregate()
    aggregate._handle_command(  # pyright: ignore[reportPrivateUsage]
        CreateWorkflowTemplateCommand(
            aggregate_id=WORKFLOW_ID,
            name="Tagged",
            workflow_type=WorkflowType.RESEARCH,
            classification=WorkflowClassification.SIMPLE,
            repository_url="",
            requires_repos=False,
            phases=[PhaseDefinition(phase_id="p1", name="P1", order=1)],
            tags=TagSet(tags),
        )
    )
    await repository.save_new(aggregate)


async def _replayed_tags(repository: RepositoryAdapter[WorkflowTemplateAggregate]) -> TagSet:
    reloaded = await repository.get_by_id(WORKFLOW_ID)
    assert reloaded is not None
    return reloaded.tags


@pytest.mark.unit
class TestAddWorkflowTags:
    async def test_added_tags_replay_from_the_stream(self) -> None:
        repository, publisher = _repository(), _Publisher()
        await _workflow_with(repository, ["nightly"])

        result = await AddWorkflowTagsHandler(repository, publisher).handle(
            AddWorkflowTagsCommand(aggregate_id=WORKFLOW_ID, tags=TagSet([" Release", "nightly"]))
        )

        assert result is not None
        assert result.success
        assert result.tags == TagSet(["nightly", "release"])
        assert await _replayed_tags(repository) == TagSet(["nightly", "release"])
        assert publisher.event_types == ["WorkflowTagsAdded"]

    async def test_adding_only_present_tags_writes_nothing(self) -> None:
        repository, publisher = _repository(), _Publisher()
        await _workflow_with(repository, ["nightly"])

        result = await AddWorkflowTagsHandler(repository, publisher).handle(
            AddWorkflowTagsCommand(aggregate_id=WORKFLOW_ID, tags=TagSet(["NIGHTLY"]))
        )

        assert result is not None
        assert result.success
        assert publisher.event_types == []

    async def test_going_over_the_limit_is_refused_and_nothing_is_written(self) -> None:
        repository, publisher = _repository(), _Publisher()
        existing = [f"t{i}" for i in range(MAX_TAGS)]
        await _workflow_with(repository, existing)

        result = await AddWorkflowTagsHandler(repository, publisher).handle(
            AddWorkflowTagsCommand(aggregate_id=WORKFLOW_ID, tags=TagSet(["one-more"]))
        )

        assert result is not None
        assert not result.success
        assert f"at most {MAX_TAGS} tags" in result.error
        assert await _replayed_tags(repository) == TagSet(existing)
        assert publisher.event_types == []

    async def test_an_unknown_workflow_is_none(self) -> None:
        result = await AddWorkflowTagsHandler(_repository()).handle(
            AddWorkflowTagsCommand(aggregate_id="nope", tags=TagSet(["x"]))
        )
        assert result is None

    async def test_an_empty_edit_is_refused(self) -> None:
        repository = _repository()
        await _workflow_with(repository, [])

        result = await AddWorkflowTagsHandler(repository).handle(
            AddWorkflowTagsCommand(aggregate_id=WORKFLOW_ID, tags=TagSet())
        )

        assert result is not None
        assert not result.success
        assert "At least one tag" in result.error


@pytest.mark.unit
class TestRemoveWorkflowTags:
    async def test_removed_tags_are_gone_on_replay(self) -> None:
        repository, publisher = _repository(), _Publisher()
        await _workflow_with(repository, ["a", "b", "c"])

        result = await RemoveWorkflowTagsHandler(repository, publisher).handle(
            RemoveWorkflowTagsCommand(aggregate_id=WORKFLOW_ID, tags=TagSet(["b", "absent"]))
        )

        assert result is not None
        assert result.success
        assert await _replayed_tags(repository) == TagSet(["a", "c"])
        assert publisher.event_types == ["WorkflowTagsRemoved"]

    async def test_removing_absent_tags_writes_nothing(self) -> None:
        repository, publisher = _repository(), _Publisher()
        await _workflow_with(repository, ["a"])

        result = await RemoveWorkflowTagsHandler(repository, publisher).handle(
            RemoveWorkflowTagsCommand(aggregate_id=WORKFLOW_ID, tags=TagSet(["b"]))
        )

        assert result is not None
        assert result.success
        assert publisher.event_types == []


@pytest.mark.unit
class TestYamlTagsReachTheStream:
    async def test_yaml_tags_survive_install_and_replay(self) -> None:
        """YAML -> definition -> command -> REAL create handler -> stream (#967).

        Each hop copies the field by hand, so each is a place it can drop.
        Asserted on a fresh load of the stream, not on the command.
        """
        from syn_domain.contexts.orchestration._shared.workflow_definition import (
            WorkflowDefinition,
        )
        from syn_domain.contexts.orchestration._shared.yaml_to_command import (
            build_command_from_definition,
        )
        from syn_domain.contexts.orchestration.slices.create_workflow_template.CreateWorkflowTemplateHandler import (
            CreateWorkflowTemplateHandler,
        )
        from syn_shared.agents import PhaseModelDefaults

        definition = WorkflowDefinition.from_yaml(
            f"id: {WORKFLOW_ID}\n"
            "name: Tagged\n"
            "type: research\n"
            "tags: [Nightly, eval-a]\n"
            "phases:\n"
            "  - id: p1\n"
            "    name: P1\n"
            "    order: 1\n"
            "    prompt_template: do it\n"
        )
        repository, publisher = _repository(), _Publisher()

        await CreateWorkflowTemplateHandler(
            repository, publisher, model_defaults=PhaseModelDefaults()
        ).handle(build_command_from_definition(definition))

        assert await _replayed_tags(repository) == TagSet(["eval-a", "nightly"])
