"""A phase's artifact declarations must be visible on the workflow detail API (#1176).

`GET /api/v1/workflows/{id}` returned phases with no `input_artifact_types` and
no `output_artifact_types` -- the keys were ABSENT from the JSON, not null. The
declarations were on disk, in the domain, in the projection and in the read
model the whole time; the endpoint rebuilt every phase into a second,
hand-maintained response model that simply did not list them.

Why that specific shape of bug is worth its own file: `p.get("output_artifact_types")`
returns `None` for a missing key exactly as it does for a null value, so reading
the endpoint led to the conclusion that no phase in `sdlc-implement-v1` declares
outputs -- and therefore that #1173's "a phase must produce what it declares"
enforcement was inert on our main workflow. The declarations are there. The
endpoint could not express the difference between "declares nothing" and "we
did not tell you", and those are different facts.

So these tests assert on the REAL JSON BODY over ASGI, not on the response
object. `WorkflowResponse(...)` in-process would answer "is the field on the
model", which is the question one hop before the one that was wrong. Key
presence is only observable after serialization, and key presence is the bug.
`model_dump()` is not a substitute: it reports the model's own fields, so it
answers the same one-hop-early question that let this through.

Why the tests drive the route rather than `_map_phases`: `_map_phases` was
already correct throughout, and `test_phase_fields_are_readable.py` covers it
-- every one of its assertions passed for the whole life of this bug. The loss
happened one hop later, where the endpoint rebuilt an already-complete phase
model into a second, route-local one. Testing either END of that hop sees
nothing, which is why the guard written for #1013 did not catch #1176.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
import yaml

if TYPE_CHECKING:
    from collections.abc import Mapping

# In-memory adapters, as the other service-level workflow tests do.
os.environ.setdefault("APP_ENVIRONMENT", "test")

from syn_api.routes.workflows.commands import create_workflow_from_yaml
from syn_api.types import Ok

# CI runs `pytest -m unit` / `-m integration`; an unmarked test never runs
# there. These use in-memory adapters and no external services.
pytestmark = pytest.mark.unit

#: The workflow this issue was reported against, resolved from this file rather
#: than from the process cwd so the drift test fails loudly if the workflow is
#: moved instead of silently skipping.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_SDLC_IMPLEMENT_YAML = _REPO_ROOT / "workflows" / "sdlc" / "implement" / "workflow.yaml"


@pytest.fixture(autouse=True)
def _reset_storage():
    from syn_adapters.projection_stores import get_projection_store
    from syn_adapters.projections.manager import reset_projection_manager
    from syn_adapters.storage import reset_storage

    reset_storage()
    reset_projection_manager()
    store = get_projection_store()
    if hasattr(store, "_data"):
        store._data.clear()
    if hasattr(store, "_state"):
        store._state.clear()
    yield
    reset_storage()
    reset_projection_manager()


async def _get_workflow_json(workflow_id: str) -> Mapping[str, Any]:
    """Fetch the workflow detail as a caller receives it: parsed JSON bytes.

    Routed through FastAPI rather than by calling the endpoint function, so
    the response model's serialization -- which is what decides whether a key
    appears at all -- is the thing under test.
    """
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from syn_api.routes.workflows.queries import router

    app = FastAPI()
    app.include_router(router)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/workflows/{workflow_id}")

    assert response.status_code == 200, response.text
    body: Mapping[str, Any] = response.json()
    return body


def _phases_by_id(body: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    phases: list[Mapping[str, Any]] = body["phases"]
    return {p["phase_id"]: p for p in phases}


# ---------------------------------------------------------------------------
# (a) Declared artifacts reach the caller, per phase
# ---------------------------------------------------------------------------

#: Two phases with DIFFERENT, non-default declarations. Distinct per phase
#: because a mapping that collapses every phase onto the first one's values --
#: or onto the workflow's -- passes any single-phase fixture. None of these
#: strings can arise from a default: the default is an empty list.
_DECLARING_YAML = """
id: declaring-wf
name: Declaring Workflow
type: implementation
classification: standard

phases:
  - id: design
    name: Design
    order: 1
    prompt_template: "Design it."
    input_artifacts: []
    output_artifacts:
      - design_doc

  - id: build
    name: Build
    order: 2
    prompt_template: "Build it."
    input_artifacts:
      - design_doc
    output_artifacts:
      - patch
      - test_report
"""


class TestDeclaredArtifactsReachTheCaller:
    async def test_each_phase_carries_its_own_declarations(self) -> None:
        assert isinstance(await create_workflow_from_yaml(_DECLARING_YAML), Ok)

        phases = _phases_by_id(await _get_workflow_json("declaring-wf"))

        assert phases["design"]["output_artifact_types"] == ["design_doc"]
        assert phases["build"]["input_artifact_types"] == ["design_doc"]
        # Order matters: this is a declaration a caller reproduces, and a
        # set-like comparison would let a reordering through.
        assert phases["build"]["output_artifact_types"] == ["patch", "test_report"]

    async def test_the_declarations_are_not_smeared_across_phases(self) -> None:
        """The negative half of the test above.

        Asserting only that `build` has its two outputs is satisfied by a
        mapping that gives EVERY phase the same list. `design` declares one
        output and no inputs, so it pins the per-phase association.
        """
        assert isinstance(await create_workflow_from_yaml(_DECLARING_YAML), Ok)

        phases = _phases_by_id(await _get_workflow_json("declaring-wf"))

        assert phases["design"]["output_artifact_types"] != phases["build"]["output_artifact_types"]
        assert phases["design"]["input_artifact_types"] == []


# ---------------------------------------------------------------------------
# (b) Absent and empty must be distinguishable -- the point of the issue
# ---------------------------------------------------------------------------

_SILENT_YAML = """
id: silent-wf
name: Silent Workflow
type: research
classification: simple

phases:
  - id: think
    name: Think
    order: 1
    prompt_template: "Think about it."
"""


class TestAPhaseDeclaringNothingSaysSo:
    """ "Declares nothing" and "we did not tell you" are different answers.

    A phase that omits both keys in its YAML must come back with both keys
    PRESENT and empty. `assert phase["input_artifact_types"] == []` alone
    cannot fail the way this bug failed -- a missing key raises `KeyError`
    rather than reporting the absence -- so presence is asserted separately
    and first, against the parsed JSON where absence is observable at all.
    """

    async def test_both_keys_are_present_when_nothing_is_declared(self) -> None:
        assert isinstance(await create_workflow_from_yaml(_SILENT_YAML), Ok)

        (phase,) = (await _get_workflow_json("silent-wf"))["phases"]

        assert "input_artifact_types" in phase
        assert "output_artifact_types" in phase

    async def test_the_present_keys_are_empty_not_null(self) -> None:
        """Empty list, not `None`.

        `null` would reintroduce the ambiguity from the other side: a caller
        doing `p.get("output_artifact_types") or []` cannot then distinguish
        a phase that declares nothing from one the API failed to answer for.
        """
        assert isinstance(await create_workflow_from_yaml(_SILENT_YAML), Ok)

        (phase,) = (await _get_workflow_json("silent-wf"))["phases"]

        assert phase["input_artifact_types"] == []
        assert phase["output_artifact_types"] == []


# ---------------------------------------------------------------------------
# (c) The endpoint and the file on disk cannot drift
# ---------------------------------------------------------------------------


def _declared_in_yaml() -> dict[str, tuple[list[str], list[str]]]:
    """Expected declarations, read from the YAML with a plain parser.

    Deliberately NOT via `WorkflowDefinition`: building the expectation with
    the same code the response is built from would make the comparison
    self-satisfying, and the `input_artifacts` -> `input_artifact_types`
    rename is one of the hops this is meant to pin.
    """
    raw = yaml.safe_load(_SDLC_IMPLEMENT_YAML.read_text(encoding="utf-8"))
    return {
        phase["id"]: (
            list(phase.get("input_artifacts") or []),
            list(phase.get("output_artifacts") or []),
        )
        for phase in raw["phases"]
    }


async def _install_sdlc_implement() -> None:
    """Install the real workflow the way the seeder does.

    `create_workflow_from_yaml` cannot be used here: the file uses
    `prompt_file:` references, which the server refuses because it has no
    base directory to resolve them against. `from_file` is the loader that
    does have one, and is what actually puts this workflow into a running
    system.
    """
    from syn_api._wiring import (
        ensure_connected,
        get_publisher,
        get_workflow_repo,
        sync_published_events_to_projections,
    )
    from syn_domain.contexts.orchestration import (
        CreateWorkflowTemplateHandler,
        WorkflowDefinition,
        build_command_from_definition,
    )

    definition = WorkflowDefinition.from_file(_SDLC_IMPLEMENT_YAML)
    await ensure_connected()
    handler = CreateWorkflowTemplateHandler(
        repository=get_workflow_repo(),
        event_publisher=get_publisher(),
    )
    await handler.handle(build_command_from_definition(definition))
    await sync_published_events_to_projections()


class TestTheEndpointMatchesTheFileOnDisk:
    """The regression guard named in #1176.

    Reading `sdlc-implement-v1` off this endpoint is how someone checks what a
    phase is wired to consume and produce. If the file and the response can
    disagree, that check is worthless, and it disagreed completely.
    """

    def test_the_fixture_is_not_vacuous(self) -> None:
        """A guard on the FILE, not on the code.

        A drift test whose expectation is empty passes against anything, so
        emptying `workflow.yaml` must fail here rather than quietly turning
        the tests below into no-ops. The last two assertions are what keep
        the drift test covering the absent-versus-empty case: it only does so
        while the workflow still declares both an empty list and a populated
        one, and if someone gives every phase an input that stops being true
        silently.
        """
        declared = _declared_in_yaml()

        assert len(declared) == 4, f"expected four phases on disk, found {len(declared)}"
        assert any(outputs for _, outputs in declared.values())
        assert [] in [inputs for inputs, _ in declared.values()], (
            "no phase declares an empty input list any more"
        )
        assert any(inputs for inputs, _ in declared.values())

    async def test_every_phase_matches_its_declaration(self) -> None:
        declared = _declared_in_yaml()
        await _install_sdlc_implement()

        phases = _phases_by_id(await _get_workflow_json("sdlc-implement-v1"))

        assert set(phases) == set(declared)
        actual = {
            phase_id: (p["input_artifact_types"], p["output_artifact_types"])
            for phase_id, p in phases.items()
        }
        assert actual == declared

    async def test_the_phase_declaring_no_inputs_still_reports_the_key(self) -> None:
        """`bootstrap` writes `input_artifacts: []` -- the real instance of the
        empty-versus-absent case, in the workflow this issue was filed about."""
        await _install_sdlc_implement()

        bootstrap = _phases_by_id(await _get_workflow_json("sdlc-implement-v1"))["bootstrap"]

        assert "input_artifact_types" in bootstrap
        assert bootstrap["input_artifact_types"] == []
        assert bootstrap["output_artifact_types"] == ["markdown"]
