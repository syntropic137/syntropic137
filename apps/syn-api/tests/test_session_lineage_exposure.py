"""Delegation lineage must survive the domain -> API boundary.

#895 threads `parent_session_id` and `root_session_id` so a delegated session
can be told from the leader that spawned it. The domain read model has carried
both for some time; the API's `SessionSummary` did not declare them, and the
route's field-by-field conversion omitted them. So the linkage existed and
nothing outside the domain could read it - no API field, no CLI type, no
dashboard column.

That is the failure this guards: not a value that is wrong, but a value that is
correct and unreachable. Nothing went red, because nothing asked.
"""

from __future__ import annotations

from typing import ClassVar

import pytest

from syn_api.types import SessionDetail, SessionSummary
from syn_domain.pagination import Page

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("model", [SessionSummary, SessionDetail])
def test_api_model_declares_the_lineage_fields(model: type) -> None:
    """A field absent from the response model cannot be returned however
    faithfully the route populates it."""
    fields = model.model_fields
    assert "parent_session_id" in fields, (
        f"{model.__name__} must expose parent_session_id; without it a delegate "
        "is indistinguishable from a leader in every client (#895)"
    )
    assert "root_session_id" in fields


@pytest.mark.parametrize("model", [SessionSummary, SessionDetail])
def test_lineage_is_optional_because_a_leader_has_no_parent(model: type) -> None:
    """Optional, not defaulted to the session's own id. A leader genuinely has
    no parent, and inventing self-parentage would make the chain unwalkable."""
    built = model(id="s-1")
    assert built.parent_session_id is None
    assert built.root_session_id is None


def test_summary_round_trips_lineage_from_an_object() -> None:
    """`from_attributes` is how the route builds these; if the field is declared
    but the source attribute is not read, this catches it."""

    class _DomainRow:
        id = "child-1"
        workflow_id = None
        execution_id = "exec-1"
        phase_id = "p-1"
        parent_session_id = "leader-1"
        root_session_id = "leader-1"
        status = "completed"
        agent_type = "claude"
        repos: ClassVar[list[str]] = []
        input_tokens = output_tokens = 0
        cache_creation_tokens = cache_read_tokens = total_tokens = 0
        started_at = completed_at = None

    s = SessionSummary.model_validate(_DomainRow())
    assert s.parent_session_id == "leader-1"
    assert s.root_session_id == "leader-1"


def test_lineage_appears_in_the_serialised_payload() -> None:
    """The keys must reach the wire. A field that exists on the model and is
    excluded from the dump is the same defect one layer further out."""
    payload = SessionSummary(
        id="child-1", parent_session_id="leader-1", root_session_id="leader-1"
    ).model_dump(mode="json")
    assert payload["parent_session_id"] == "leader-1"
    assert payload["root_session_id"] == "leader-1"


@pytest.mark.asyncio
async def test_the_ROUTE_carries_lineage_from_the_projection() -> None:
    """The assertion the model-level tests above cannot make.

    The original defect was NOT a missing field on the response model - it was
    the route's field-by-field conversion silently omitting two attributes the
    domain row already had. Deleting those two lines from `list_sessions` leaves
    every model test green, because the model still declares the fields and
    still round-trips them when something bothers to pass them.

    Verified: with the conversion lines removed, the whole syn-api suite passed
    592/592. This test is the one that goes red.
    """
    from unittest.mock import AsyncMock, MagicMock, patch

    from syn_api.routes.sessions import list_sessions

    class _DomainRow:
        id = "child-1"
        workflow_id = "wf-1"
        execution_id = "exec-1"
        phase_id = "p-1"
        parent_session_id = "leader-1"
        root_session_id = "leader-1"
        status = "completed"
        agent_type = "claude"
        repos: ClassVar[list[str]] = []
        input_tokens = output_tokens = 0
        cache_creation_tokens = cache_read_tokens = total_tokens = 0
        started_at = completed_at = None

    manager = MagicMock()
    manager.session_list.page = AsyncMock(
        return_value=Page(rows=[_DomainRow()], total=1, status_counts={"completed": 1})
    )

    with (
        patch("syn_api.routes.sessions.ensure_connected", new_callable=AsyncMock) as ensure,
        patch("syn_api.routes.sessions.get_projection_mgr", return_value=manager),
    ):
        result = await list_sessions()
        ensure.assert_awaited_once()

    sessions = result.value.rows
    assert len(sessions) == 1
    assert sessions[0].parent_session_id == "leader-1", (
        "the route must copy parent_session_id off the domain row; dropping it "
        "is the exact defect this PR fixes, and no model-level test sees it"
    )
    assert sessions[0].root_session_id == "leader-1"


class TestLineageReachesTheWire:
    """The assertion that catches what every test above missed.

    My first attempt added the fields to `SessionSummary`/`SessionDetail` in
    types.py and tested those. Both passed, and both mutation-tested clean. But
    the HTTP surface is served by `SessionSummaryResponse` and `SessionResponse`
    defined in routes/sessions.py, so the change reached no client at all: the
    OpenAPI spec had `SessionSummaryResponse` with no lineage, and the generated
    CLI and dashboard types had nothing.

    Testing the model I edited could not tell me I had edited the wrong model.
    Only asserting against the SERVED schema can.
    """

    @staticmethod
    def _spec() -> dict:
        import json
        import pathlib

        root = pathlib.Path(__file__).resolve().parents[3]
        return json.loads((root / "apps" / "syn-docs" / "openapi.json").read_text())

    @pytest.mark.parametrize("schema", ["SessionSummaryResponse", "SessionResponse"])
    def test_served_schema_carries_lineage(self, schema: str) -> None:
        props = self._spec()["components"]["schemas"][schema]["properties"]
        assert "parent_session_id" in props, (
            f"{schema} is what the HTTP API actually returns. A field present on "
            "an internal model and absent here reaches no client (#895)."
        )
        assert "root_session_id" in props

    @pytest.mark.parametrize(
        "generated",
        [
            "apps/syn-cli-node/src/generated/api-types.ts",
            "apps/syn-dashboard-ui/src/generated/api-types.ts",
        ],
    )
    def test_generated_client_types_carry_lineage(self, generated: str) -> None:
        """Guards the codegen step, not the model.

        These are regenerated from the spec, so a change that skips codegen
        leaves clients typed without the field while the API returns it - and
        the drift is invisible from the Python side.
        """
        import pathlib

        root = pathlib.Path(__file__).resolve().parents[3]
        text = (root / generated).read_text()
        assert "parent_session_id" in text, f"{generated} is stale; run `just codegen`"
        assert "root_session_id" in text
