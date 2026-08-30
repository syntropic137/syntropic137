"""A phase field that is stored must be readable (#1013).

#1012 fixed the create path so `provider`, `allow_delegation`, `claude_plugins`
and `skills` reach the domain. Three of the four then vanished: absent from the
detail projection, the read model, and the API response. Stored correctly and
invisible.

That is worse than a plain omission, and it is the same failure #1011 was
about. `GET /workflows/{id}` could not tell you whether a phase declares
skills, plugins, or delegation -- so you install a workflow, ask the API what
it installed, and the answer omits exactly the fields you are most likely to
have got wrong. I found the missing `provider` only because a run cost 7x less
than expected; had GET shown these fields it would have been obvious in
seconds.

The tests here deliberately cross boundaries rather than assert presence layer
by layer. Per-layer checks all pass while the data is lost at a seam BETWEEN
them, which is precisely how the create-path drop survived.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from syn_api.routes.workflows.commands import _build_phase_defs
from syn_domain.contexts.orchestration.domain.read_models.workflow_detail import WorkflowDetail
from syn_domain.contexts.orchestration.slices.get_workflow_detail.projection import (
    WorkflowDetailProjection,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

pytestmark = pytest.mark.unit

#: One phase declaring every field a reader needs to see.
_DECLARED: Mapping[str, object] = {
    "phase_id": "review",
    "name": "Review",
    "order": 1,
    "provider": "codex",
    "model": "gpt-5.6-sol",
    "allow_delegation": True,
    "claude_plugins": ["owner/repo@abc123"],
    "skills": ["owner/repo/some-skill@abc123"],
}


class _Store:
    """Records what the projection wrote, keyed as the real store does."""

    def __init__(self) -> None:
        self.rows: dict[str, Mapping[str, object]] = {}

    async def save(self, _name: str, key: str, data: Mapping[str, object]) -> None:
        self.rows[key] = data

    async def get(self, _name: str, key: str) -> Mapping[str, object] | None:
        return self.rows.get(key)


def _created_event() -> Mapping[str, object]:
    """The event a create actually emits, built through the real converter.

    Hand-writing this payload would let it drift from what `_build_phase_defs`
    produces, and then the test would pass against a shape production never
    emits.
    """
    (phase,) = _build_phase_defs([dict(_DECLARED)])
    return {
        "workflow_id": "wf-1",
        "name": "Test",
        "workflow_type": "custom",
        "phases": [phase.model_dump(mode="json")],
    }


class TestTheProjectionKeepsWhatCreateStored:
    """The first seam: event -> projected row."""

    async def test_delegation_survives_projection(self) -> None:
        store = _Store()
        projection = WorkflowDetailProjection(store)

        await projection.on_workflow_template_created(_created_event())

        (row,) = store.rows.values()
        phases = row["phases"]
        assert isinstance(phases, list)
        assert phases[0]["allow_delegation"] is True

    async def test_skills_survive_projection(self) -> None:
        store = _Store()
        projection = WorkflowDetailProjection(store)

        await projection.on_workflow_template_created(_created_event())

        (row,) = store.rows.values()
        phases = row["phases"]
        assert isinstance(phases, list)
        assert len(phases[0]["skills"]) == 1

    async def test_plugins_survive_projection(self) -> None:
        store = _Store()
        projection = WorkflowDetailProjection(store)

        await projection.on_workflow_template_created(_created_event())

        (row,) = store.rows.values()
        phases = row["phases"]
        assert isinstance(phases, list)
        assert len(phases[0]["claude_plugins"]) == 1

    async def test_provider_still_survives(self) -> None:
        """The one field that already worked. Kept so a refactor cannot trade
        three newly-readable fields for the one that was fine."""
        store = _Store()
        projection = WorkflowDetailProjection(store)

        await projection.on_workflow_template_created(_created_event())

        (row,) = store.rows.values()
        phases = row["phases"]
        assert isinstance(phases, list)
        assert phases[0]["provider"] == "codex"


class TestALegacyRowStillReads:
    """Rows written before these fields existed carry nothing for them.

    The response model must not reject them, and must not invent a value that
    claims the phase asked for something it did not.
    """

    async def test_a_phase_without_the_fields_reads_as_declaring_nothing(self) -> None:
        store = _Store()
        projection = WorkflowDetailProjection(store)

        await projection.on_workflow_template_created(
            {
                "workflow_id": "wf-legacy",
                "name": "Legacy",
                "workflow_type": "custom",
                "phases": [{"phase_id": "p", "name": "P", "order": 1}],
            }
        )

        (row,) = store.rows.values()
        phases = row["phases"]
        assert isinstance(phases, list)
        assert phases[0].get("allow_delegation") is False
        assert not phases[0].get("skills")
        assert not phases[0].get("claude_plugins")


class TestTheRowReadsBackOut:
    """The seam the first version of this PR missed entirely.

    `to_dict` wrote the fields and `from_dict` dropped them, so the value
    reached the store and was discarded on the way back. EVERY reader -- the
    API, the export, the CLI -- goes through `from_dict`, so half the path was
    fixed while five tests passed.

    The tests above stop at the store. That is one boundary, and this bug lived
    at the next one. Asserting on the write side alone cannot see it.
    """

    def test_a_stored_row_reconstructs_with_its_fields(self) -> None:
        row = {
            "id": "wf-1",
            "name": "T",
            "workflow_type": "custom",
            "phases": [
                {
                    "id": "p",
                    "name": "P",
                    "order": 1,
                    "provider": "codex",
                    "allow_delegation": True,
                    "claude_plugins": [{"source_url": "https://github.com/foo/bar", "name": "bar"}],
                    "skills": [{"source_url": "https://github.com/a/b", "skill_name": "alpha"}],
                }
            ],
        }

        phase = WorkflowDetail.from_dict(row).phases[0]

        assert phase.allow_delegation is True
        assert phase.claude_plugins[0].source_url == "https://github.com/foo/bar"
        assert phase.skills[0].name == "alpha"

    def test_a_full_round_trip_preserves_the_refs(self) -> None:
        """to_dict -> from_dict must be identity for these fields."""
        row = {
            "id": "wf-1",
            "name": "T",
            "workflow_type": "custom",
            "phases": [
                {
                    "id": "p",
                    "name": "P",
                    "order": 1,
                    "allow_delegation": True,
                    "skills": [
                        {
                            "source_url": "https://github.com/a/b",
                            "skill_name": "alpha",
                            "version": "v1",
                            "name_overridden": True,
                        }
                    ],
                }
            ],
        }

        once = WorkflowDetail.from_dict(row)
        twice = WorkflowDetail.from_dict(once.to_dict())

        assert once.phases[0].skills == twice.phases[0].skills
        assert twice.phases[0].skills[0].name_overridden is True


class TestRefsAreNotFlattened:
    """Joining source and name is not reversible.

    The first version rendered `source/name@version`. A ref whose source
    already ends in the repo name became `.../bar/bar@v1`, which reparses to a
    DIFFERENT repository -- and two refs differing only in `name_overridden`
    rendered identically. A renderer that confidently returns the wrong
    identity is worse than the omission it replaced, because callers copy and
    export the corruption.
    """

    def test_the_source_is_not_mangled_by_the_name(self) -> None:
        row = {
            "id": "wf-1",
            "name": "T",
            "workflow_type": "custom",
            "phases": [
                {
                    "id": "p",
                    "name": "P",
                    "order": 1,
                    "claude_plugins": [
                        {"source_url": "https://github.com/foo/bar", "name": "bar", "version": "v1"}
                    ],
                }
            ],
        }

        ref = WorkflowDetail.from_dict(row).phases[0].claude_plugins[0]

        assert ref.source_url == "https://github.com/foo/bar"
        assert ref.name == "bar"

    def test_two_refs_differing_only_in_name_overridden_stay_distinct(self) -> None:
        base = {"source_url": "https://github.com/a/b", "skill_name": "s", "version": "v1"}
        row = {
            "id": "wf-1",
            "name": "T",
            "workflow_type": "custom",
            "phases": [
                {
                    "id": "p",
                    "name": "P",
                    "order": 1,
                    "skills": [
                        {**base, "name_overridden": True},
                        {**base, "name_overridden": False},
                    ],
                }
            ],
        }

        skills = WorkflowDetail.from_dict(row).phases[0].skills

        assert skills[0] != skills[1]
