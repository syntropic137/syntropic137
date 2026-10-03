"""The producing agent's identity must survive event -> projection -> read model (#1284).

A cross-model review's whole value is that a DIFFERENT model checked the work,
and no stored artifact could show which one did: every review artifact opened by
saying it could not determine the models that ran its own phases. The fix adds
``agent_provider``/``agent_model`` to ArtifactCreated v6, so what this walks is
the chain those two have to cross rather than any single hop - a test of the
aggregate alone passes while the projection drops the field, and a test of the
projection alone passes while the read model cannot read its own dict back.

The values below are chosen so no hop can pass by accident. ``codex`` paired
with a claude model is a combination nothing in the system would produce from
configuration, so a row carrying it can only have come from the payload.
"""

from __future__ import annotations

import pytest

from syn_domain.contexts.artifacts import (
    UNREPORTED_AGENT,
    AgentIdentity,
    ArtifactAggregate,
    ArtifactType,
    CreateArtifactCommand,
)
from syn_domain.contexts.artifacts.domain.read_models.artifact_summary import (
    ArtifactSummary,
)
from syn_domain.contexts.artifacts.slices.list_artifacts.projection import (
    ArtifactListProjection,
)

pytestmark = pytest.mark.unit

PROVIDER = "codex"
#: Deliberately mismatched with PROVIDER: a claude model name on a codex phase.
#: Nothing configures this pair, so it cannot be reconstructed from config - if
#: it comes back, it came from the recorded fact.
ANNOUNCED_MODEL = "claude-sonnet-4-5-20250929"


#: What ``ArtifactSummary.to_dict`` actually emits.
ProjectionRow = dict[str, str | int | None]


class _Store:
    """Minimal projection store: records what the projection wrote."""

    def __init__(self) -> None:
        self.rows: dict[str, ProjectionRow] = {}

    async def save(self, _name: str, key: str, data: ProjectionRow) -> None:
        self.rows[key] = data


def _payload(artifact_id: str, **extra: str) -> dict[str, str]:
    return {
        "artifact_id": artifact_id,
        "workflow_id": "wf-1",
        "execution_id": "exec-1",
        "phase_id": "verify",
        "artifact_type": "markdown",
        "title": "Verify: artifacts/output/deliverable.md",
        "content": "the review",
        **extra,
    }


class TestTheEventCarriesWhoProducedIt:
    def test_both_halves_reach_the_aggregate(self) -> None:
        aggregate = ArtifactAggregate()
        aggregate.create_artifact(
            CreateArtifactCommand(
                aggregate_id="art-1",
                workflow_id="wf-1",
                phase_id="verify",
                artifact_type=ArtifactType.MARKDOWN,
                content="the review",
                title="Verify",
                agent_provider=PROVIDER,
                agent_model=ANNOUNCED_MODEL,
            )
        )
        assert aggregate.agent == AgentIdentity(provider=PROVIDER, model=ANNOUNCED_MODEL)

    def test_a_provider_that_announced_no_model_keeps_a_none_model(self) -> None:
        """Every codex phase today. The provider alone still proves which
        harness ran, and the model stays absent rather than being filled in
        from the phase's configuration - a requested value under the name of
        the one that ran would read as proof and be none.
        """
        aggregate = ArtifactAggregate()
        aggregate.create_artifact(
            CreateArtifactCommand(
                aggregate_id="art-2",
                workflow_id="wf-1",
                phase_id="verify",
                artifact_type=ArtifactType.MARKDOWN,
                content="the review",
                title="Verify",
                agent_provider=PROVIDER,
            )
        )
        assert aggregate.agent == AgentIdentity(provider=PROVIDER, model=None)

    def test_an_artifact_no_phase_produced_reports_nothing(self) -> None:
        """Created directly through the API, so no harness ran and there is
        nothing to report - distinct from "ran and did not say"."""
        aggregate = ArtifactAggregate()
        aggregate.create_artifact(
            CreateArtifactCommand(
                aggregate_id="art-3",
                workflow_id="wf-1",
                phase_id="",
                artifact_type=ArtifactType.MARKDOWN,
                content="hand-made",
                title="Manual",
            )
        )
        assert aggregate.agent == UNREPORTED_AGENT


class TestTheProjectionPersistsIt:
    async def test_both_fields_are_written_to_the_read_model(self) -> None:
        store = _Store()
        projection = ArtifactListProjection(store)
        await projection.on_artifact_created(
            _payload("art-1", agent_provider=PROVIDER, agent_model=ANNOUNCED_MODEL)
        )
        assert store.rows["art-1"]["agent_provider"] == PROVIDER
        assert store.rows["art-1"]["agent_model"] == ANNOUNCED_MODEL

    async def test_a_pre_v6_event_projects_nulls(self) -> None:
        """Deserialization resolves on event TYPE and ignores the stored
        version, so no upcaster runs and a v5 payload simply lacks the keys.
        Reading them must leave nulls, not raise and not invent.
        """
        store = _Store()
        projection = ArtifactListProjection(store)
        await projection.on_artifact_created(_payload("art-2"))
        assert store.rows["art-2"]["agent_provider"] is None
        assert store.rows["art-2"]["agent_model"] is None

    def test_the_read_model_round_trips_both_through_a_dict(self) -> None:
        """The projection store persists dicts, so a field the read model can
        write but not read back is lost on the rebuild path specifically."""
        original = ArtifactSummary(
            id="art-1",
            workflow_id="wf-1",
            execution_id="exec-1",
            session_id=None,
            phase_id="verify",
            artifact_type="markdown",
            name="Verify",
            created_at=None,
            content="the review",
            agent_provider=PROVIDER,
            agent_model=ANNOUNCED_MODEL,
        )
        restored = ArtifactSummary.from_dict(original.to_dict())
        assert (restored.agent_provider, restored.agent_model) == (PROVIDER, ANNOUNCED_MODEL)
