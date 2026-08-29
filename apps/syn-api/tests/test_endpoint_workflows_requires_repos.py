"""The workflow list must report the real requires_repos, not a model default (#955).

Measured on a live deployment: the list endpoint reported `requires_repos: True`
for all 36 workflows, while the detail endpoint reported False for 20 of them.
The stored rows agreed with detail -- both `workflow_summaries` and
`workflow_details` had 36 rows, all carrying the key, 20 of them false.

The projection and the event were innocent. The list endpoint simply omitted the
field when building `WorkflowSummaryResponse`, so the model's `= True` default
answered for every workflow.

Why it matters: an agent that lists workflows, sees `requires_repos: True`, and
passes `-R` is told repositories are supported when they are not. The API points
the caller at the wrong conclusion.
"""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from syn_api.routes.workflows.queries import list_workflows_endpoint
from syn_api.types import Ok

pytestmark = pytest.mark.unit


@dataclass
class _Summary:
    id: str
    name: str
    requires_repos: bool
    workflow_type: str = "custom"
    classification: str | None = None
    phase_count: int = 1
    description: str | None = None
    created_at: str | None = None
    runs_count: int = 0
    is_archived: bool = False


async def _list(summaries: list[_Summary]):
    async def fake_list_workflows(*, workflow_type, limit, offset, include_archived):
        return Ok(summaries)

    mgr = MagicMock()
    mgr.workflow_list.count = AsyncMock(return_value=len(summaries))

    with (
        patch(
            "syn_api.routes.workflows.queries.list_workflows",
            new=AsyncMock(side_effect=fake_list_workflows),
        ),
        patch("syn_api.routes.workflows.queries.get_projection_mgr", return_value=mgr),
    ):
        return await list_workflows_endpoint(
            workflow_type=None,
            include_archived=False,
            page=1,
            page_size=20,
            order_by=None,
        )


async def test_false_is_reported_as_false() -> None:
    """The exact bug: a False workflow was reported True by the model default."""
    resp = await _list([_Summary(id="probe", name="probe", requires_repos=False)])
    assert resp.workflows[0].requires_repos is False


async def test_true_is_still_reported_as_true() -> None:
    resp = await _list([_Summary(id="planner", name="planner", requires_repos=True)])
    assert resp.workflows[0].requires_repos is True


async def test_a_mixed_page_preserves_each_value() -> None:
    """A default masquerading as data is only visible when the values differ."""
    resp = await _list(
        [
            _Summary(id="a", name="a", requires_repos=True),
            _Summary(id="b", name="b", requires_repos=False),
            _Summary(id="c", name="c", requires_repos=False),
        ]
    )
    assert [w.requires_repos for w in resp.workflows] == [True, False, False]
