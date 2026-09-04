"""A phase's artifact declarations must be readable off `GET /workflows/{id}` (#1176).

The declarations decide whether phases can hand work to each other: #1166 is a
phase reading an input nothing produces, and #1173 enforces that a phase
produces what it declares. Both act on values the API did not show.

The failure was not that the fields were empty -- it was that the keys were
ABSENT. Reading `output_artifact_types: None` off this endpoint, a reader
concluded no phase declared outputs and therefore that #1173's enforcement was
inert on the main workflow. It was not; the key was simply missing. A response
that cannot distinguish "declares nothing" from "we did not tell you" invites
exactly that wrong conclusion, so these tests assert on the SERIALIZED
response, where absent and empty are different things -- `model_dump()` on a
model that lacks the field cannot tell you which one you have.

Why the tests drive the route rather than `_map_phases`: `_map_phases` was
already correct. `test_phase_fields_are_readable.py` covers it, and every one
of its assertions passed throughout this bug. The loss happened one hop later,
where `get_workflow_endpoint` rebuilt an already-complete phase model field by
field into a second, route-local one. Testing either end of that hop sees
nothing. So these call the endpoint.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from syn_api.routes.workflows import queries
from syn_api.routes.workflows.commands import _build_phase_defs
from syn_domain.contexts.orchestration._shared.workflow_definition import (
    WorkflowDefinition,
)
from syn_domain.contexts.orchestration.slices.get_workflow_detail.projection import (
    WorkflowDetailProjection,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

pytestmark = pytest.mark.unit

#: The workflow the issue was reported against, and the file test (c) pins to.
_SDLC_IMPLEMENT = (
    Path(__file__).resolve().parents[3] / "workflows" / "sdlc" / "implement" / "workflow.yaml"
)


class _Store:
    """Records what the projection wrote, keyed as the real store does.

    `resolve_or_raise` takes the exact-match fast path through `get`, so the
    endpoint's prefix resolution needs nothing more than this.
    """

    def __init__(self) -> None:
        self.rows: dict[str, Mapping[str, object]] = {}

    async def save(self, _name: str, key: str, data: Mapping[str, object]) -> None:
        self.rows[key] = data

    async def get(self, _name: str, key: str) -> Mapping[str, object] | None:
        return self.rows.get(key)


class _ProjectionMgr:
    def __init__(self, store: _Store, projection: WorkflowDetailProjection) -> None:
        self.store = store
        self.workflow_detail = projection


async def _serve(
    monkeypatch: pytest.MonkeyPatch,
    workflow_id: str,
    phases: Sequence[Mapping[str, object]],
) -> dict[str, Any]:
    """Install a workflow and read it back through the real endpoint.

    Returns the SERIALIZED response, because the question this issue asks --
    is the key there? -- can only be asked of the JSON a caller receives.

    The phase payload goes through `_build_phase_defs`, the same converter the
    create route uses, so a hand-written shape cannot drift from what a real
    install emits.
    """
    store = _Store()
    projection = WorkflowDetailProjection(store)
    await projection.on_workflow_template_created(
        {
            "workflow_id": workflow_id,
            "name": "Test",
            "workflow_type": "custom",
            "phases": [
                p.model_dump(mode="json") for p in _build_phase_defs([dict(p) for p in phases])
            ],
        }
    )

    mgr = _ProjectionMgr(store, projection)
    monkeypatch.setattr(queries, "get_projection_mgr", lambda: mgr)

    async def _connected() -> None:
        return None

    monkeypatch.setattr(queries, "ensure_connected", _connected)

    response = await queries.get_workflow_endpoint(workflow_id)
    return response.model_dump(mode="json")


class TestTheDeclarationsReachTheCaller:
    """(a) What a phase declares is what the endpoint reports, per phase."""

    async def test_each_phase_carries_its_own_declarations(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Distinct values per phase, so a mapping that reuses one phase's
        lists for every phase fails here rather than passing on symmetry."""
        served = await _serve(
            monkeypatch,
            "wf-declared",
            [
                {
                    "phase_id": "research",
                    "name": "Research",
                    "order": 1,
                    "input_artifact_types": ["issue"],
                    "output_artifact_types": ["markdown", "json"],
                },
                {
                    "phase_id": "build",
                    "name": "Build",
                    "order": 2,
                    "input_artifact_types": ["markdown", "json"],
                    "output_artifact_types": ["diff"],
                },
            ],
        )

        research, build = served["phases"]
        assert research["input_artifact_types"] == ["issue"]
        assert research["output_artifact_types"] == ["markdown", "json"]
        assert build["input_artifact_types"] == ["markdown", "json"]
        assert build["output_artifact_types"] == ["diff"]


class TestDeclaringNothingIsNotTheSameAsSayingNothing:
    """(b) The distinction the whole issue is about.

    `output_artifact_types: []` means the phase produces nothing. A missing
    key means the endpoint did not answer. The first is a fact about the
    workflow; the second is a fact about the API, and reading one as the other
    is what produced the wrong conclusion in the report.
    """

    async def test_a_phase_declaring_nothing_still_has_both_keys(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        served = await _serve(
            monkeypatch,
            "wf-bare",
            [{"phase_id": "solo", "name": "Solo", "order": 1}],
        )
        (phase,) = served["phases"]

        # `in`, not truthiness: `[]` and absent are both falsy, and telling
        # them apart is the entire point.
        assert "input_artifact_types" in phase
        assert "output_artifact_types" in phase
        assert phase["input_artifact_types"] == []
        assert phase["output_artifact_types"] == []


class TestTheEndpointCannotDriftFromTheFile:
    """(c) `sdlc-implement-v1` as served must match `workflow.yaml` on disk.

    The declarations are read from the file, not restated here: a table
    written into the test would drift with the workflow and then assert
    against itself.
    """

    async def test_all_four_phases_match_their_yaml(self, monkeypatch: pytest.MonkeyPatch) -> None:
        definition = WorkflowDefinition.from_file(_SDLC_IMPLEMENT)
        declared = {
            p.id: (list(p.input_artifacts), list(p.output_artifacts)) for p in definition.phases
        }
        assert len(declared) == 4, f"expected four phases on disk, found {len(declared)}"

        served = await _serve(
            monkeypatch,
            definition.id,
            [
                {
                    "phase_id": p.phase_id,
                    "name": p.name,
                    "order": p.order,
                    "input_artifact_types": list(p.input_artifact_types),
                    "output_artifact_types": list(p.output_artifact_types),
                }
                for p in definition.get_domain_phases()
            ],
        )

        assert [p["phase_id"] for p in served["phases"]] == list(declared)
        for phase in served["phases"]:
            expected_in, expected_out = declared[phase["phase_id"]]
            assert phase["input_artifact_types"] == expected_in, phase["phase_id"]
            assert phase["output_artifact_types"] == expected_out, phase["phase_id"]

    async def test_the_file_still_exercises_both_sides_of_the_distinction(self) -> None:
        """A guard on the fixture, not on the code.

        The drift test above is only meaningful while `sdlc-implement-v1`
        still contains both an empty declaration and a populated one. If the
        workflow is edited so every phase declares something, that test stops
        covering the absent-vs-empty case silently, and this fails instead.
        """
        definition = WorkflowDefinition.from_file(_SDLC_IMPLEMENT)
        lists = [list(p.input_artifacts) for p in definition.phases]

        assert [] in lists, "no phase declares an empty input list any more"
        assert any(lists), "no phase declares a non-empty input list any more"
