"""Declared skills on the workflow LIST read model.

The workflows list draws each card's skill chips. Before the summary carried
them, the only source was the detail read model, so a page of twenty cards cost
twenty-one requests. Asserted on FRESH projections replaying what a real
repository wrote, the same way the tags tests are (#959), so a skill the event
carries but the projection drops cannot pass.
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
from syn_domain.contexts.orchestration._shared.skill_ref import SkillRef
from syn_domain.contexts.orchestration._shared.tags import TagSet
from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.value_objects import (
    PhaseDefinition,
    WorkflowClassification,
    WorkflowType,
)
from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.WorkflowTemplateAggregate import (
    WorkflowTemplateAggregate,
)
from syn_domain.contexts.orchestration.domain.commands.CreateWorkflowTemplateCommand import (
    CreateWorkflowTemplateCommand,
)
from syn_domain.contexts.orchestration.domain.commands.UpdateWorkflowTemplateCommand import (
    UpdateWorkflowTemplateCommand,
)
from syn_domain.contexts.orchestration.domain.read_models.workflow_summary import (
    WorkflowSkillSummary,
    WorkflowSummary,
    declared_skills,
)
from syn_domain.contexts.orchestration.slices.list_workflows.projection import (
    WorkflowListProjection,
)
from syn_domain.testing.stored_replay import replay

WORKFLOW_ID = "wf-skills"
SOURCE = "https://github.com/acme/skills"

REVIEW = SkillRef(skill_name="review", source_url=SOURCE, version="v1")
LINT = SkillRef(skill_name="lint", source_url=SOURCE, version="v1")
REVIEW_V2 = SkillRef(skill_name="review", source_url=SOURCE, version="v2")


def _phases(*skill_sets: tuple[SkillRef, ...]) -> list[PhaseDefinition]:
    return [
        PhaseDefinition(phase_id=f"p{i}", name=f"P{i}", order=i, skills=skills)
        for i, skills in enumerate(skill_sets, start=1)
    ]


def _create(
    phases: list[PhaseDefinition], skills: tuple[SkillRef, ...] = ()
) -> CreateWorkflowTemplateCommand:
    return CreateWorkflowTemplateCommand(
        aggregate_id=WORKFLOW_ID,
        name="Skilled",
        workflow_type=WorkflowType.RESEARCH,
        classification=WorkflowClassification.SIMPLE,
        repository_url="",
        requires_repos=False,
        phases=phases,
        skills=list(skills),
        tags=TagSet([]),
    )


def _repository(client: MemoryEventStoreClient) -> RepositoryAdapter[WorkflowTemplateAggregate]:
    return RepositoryAdapter(
        EventStoreRepository(
            client,
            WorkflowTemplateAggregate,  # type: ignore[arg-type]  # ESP SDK TEvent invariance
            "WorkflowTemplate",
        )
    )


async def _summary(client: MemoryEventStoreClient) -> WorkflowSummary:
    listing = WorkflowListProjection(InMemoryProjectionStore())
    await replay(client, MemoryCheckpointStore(), listing)
    (summary,) = await listing.get_all()
    return summary


def _names(summary: WorkflowSummary) -> list[tuple[str | None, str | None, tuple[str, ...]]]:
    return [(s.ref.name, s.ref.version, s.phase_ids) for s in summary.skills]


@pytest.mark.unit
class TestReplayBuildsDeclaredSkills:
    async def test_skills_are_collected_across_phases_once_each(self) -> None:
        client = MemoryEventStoreClient()
        aggregate = WorkflowTemplateAggregate()
        aggregate._handle_command(  # pyright: ignore[reportPrivateUsage]
            _create(_phases((REVIEW,), (LINT, REVIEW), ()))
        )
        await _repository(client).save_new(aggregate)

        summary = await _summary(client)

        assert _names(summary) == [
            ("review", "v1", ("p1", "p2")),
            ("lint", "v1", ("p2",)),
        ]
        assert summary.skills[0].ref.source_url == SOURCE

    async def test_two_versions_of_one_skill_are_two_skills(self) -> None:
        """A chip that merged them would hide which version a phase runs."""
        client = MemoryEventStoreClient()
        aggregate = WorkflowTemplateAggregate()
        aggregate._handle_command(  # pyright: ignore[reportPrivateUsage]
            _create(_phases((REVIEW,), (REVIEW_V2,)))
        )
        await _repository(client).save_new(aggregate)

        assert _names(await _summary(client)) == [
            ("review", "v1", ("p1",)),
            ("review", "v2", ("p2",)),
        ]

    async def test_a_reinstall_replaces_the_skills(self) -> None:
        client = MemoryEventStoreClient()
        repository = _repository(client)
        aggregate = WorkflowTemplateAggregate()
        aggregate._handle_command(_create(_phases((REVIEW,))))  # pyright: ignore[reportPrivateUsage]
        await repository.save_new(aggregate)

        loaded = await repository.get_by_id(WORKFLOW_ID)
        assert loaded is not None
        loaded._handle_command(  # pyright: ignore[reportPrivateUsage]
            UpdateWorkflowTemplateCommand(
                **_create(_phases((LINT,))).model_dump(
                    exclude={"force", "version", "source_digest"}
                ),
                force=True,
            )
        )
        await repository.save(loaded)

        assert _names(await _summary(client)) == [("lint", "v1", ("p1",))]

    async def test_workflow_scope_skills_are_reported_and_marked(self) -> None:
        """A workflow-scope skill reaches every phase; it is not any phase's own."""
        client = MemoryEventStoreClient()
        aggregate = WorkflowTemplateAggregate()
        aggregate._handle_command(  # pyright: ignore[reportPrivateUsage]
            _create(_phases((REVIEW,), ()), skills=(LINT, REVIEW))
        )
        await _repository(client).save_new(aggregate)

        summary = await _summary(client)
        assert [(s.ref.name, s.phase_ids, s.workflow_scope) for s in summary.skills] == [
            ("lint", (), True),
            ("review", ("p1",), True),
        ]

    async def test_a_workflow_without_skills_reports_none(self) -> None:
        client = MemoryEventStoreClient()
        aggregate = WorkflowTemplateAggregate()
        aggregate._handle_command(_create(_phases((), ())))  # pyright: ignore[reportPrivateUsage]
        await _repository(client).save_new(aggregate)

        assert (await _summary(client)).skills == ()


@pytest.mark.unit
class TestStoredRows:
    def test_round_trips_through_storage(self) -> None:
        (skill,) = declared_skills(
            [
                {
                    "id": "p1",
                    "skills": [{"skill_name": "review", "source_url": SOURCE, "version": "v1"}],
                }
            ]
        )
        summary = WorkflowSummary(
            id="wf",
            name="wf",
            workflow_type="custom",
            classification="simple",
            phase_count=1,
            description=None,
            created_at=None,
            skills=(skill,),
        )
        assert WorkflowSummary.from_dict(summary.to_dict()).skills == (skill,)

    def test_a_row_written_before_skills_reads_as_none(self) -> None:
        row = {"id": "wf", "name": "wf"}
        assert WorkflowSummary.from_dict(row).skills == ()

    def test_an_unreadable_stored_skill_is_dropped_not_blanked(self) -> None:
        assert WorkflowSkillSummary.from_stored({"ref": {}, "phase_ids": ["p1"]}) is None
        assert WorkflowSkillSummary.from_stored("nonsense") is None

    def test_a_shorthand_ref_is_kept_whole(self) -> None:
        (skill,) = declared_skills([{"id": "p1", "skills": ["acme/skills/review@v1"]}])
        assert skill.ref.raw == "acme/skills/review@v1"
        assert skill.phase_ids == ("p1",)

    def test_name_overridden_does_not_split_one_skill(self) -> None:
        """Identity is (source, version, name), as ``SkillRef`` compares."""
        ref = {"skill_name": "review", "source_url": SOURCE, "version": "v1"}
        (skill,) = declared_skills(
            [
                {"id": "p1", "skills": [ref]},
                {"id": "p2", "skills": [{**ref, "name_overridden": True}]},
            ]
        )
        assert skill.phase_ids == ("p1", "p2")
