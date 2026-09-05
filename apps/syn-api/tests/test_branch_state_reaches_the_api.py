"""#1200: an API client can act on where a failed phase's branches stand.

The domain records four states for a failed phase - a remote ref that moved,
commits on no remote at all, `()` for "we read git and nothing differs from how
the phase found it", and None for "nobody could read it". Three of those four
read the same in prose ("no branch to fetch"), so the difference only survives
as structure. These pin BOTH mapping hops, because either one dropping a field
puts the client back to reading sentences: that is exactly how #891 shipped,
with the field declared at both ends and lost in the middle.

NOTHING HERE IS AN ATTRIBUTION, and the field names are the load-bearing part.
`remote_commit` and `remote_commit_at_phase_start` are two readings of one ref;
a client comparing them learns that it moved, which is all git can say. An
earlier version of this API called the same data `pushed_work`, which claimed
the phase had done the moving - a claim no ref inspection can support.
"""

from __future__ import annotations

import pytest

from syn_api.routes.executions.queries import _map_phase_detail, _map_phase_to_response
from syn_api.types import BranchObservationInfo, PhaseExecution
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    BranchObservation,
)
from syn_domain.contexts.orchestration.domain.read_models.workflow_execution_detail import (
    PhaseExecutionDetail,
)

pytestmark = pytest.mark.unit

_BRANCH = "fix/1187-open-pr-bootstrap-overhead"
_STARTED_AT = "3c4d5e6f708192a3b4c5d6e7f8091a2b3c4d5e6f"
_NOW = "9f2c1a4e6b7d8c0f1e2a3b4c5d6e7f8091a2b3c4"

#: The incident: the ref this workspace was on is not where the phase found it.
_MOVED = BranchObservation(
    repo="syntropic137",
    branch=_BRANCH,
    remote="origin",
    remote_commit=_NOW,
    remote_commit_at_phase_start=_STARTED_AT,
    unpushed_commits=0,
)

#: The other incident: the ref never moved, and commits here are on no remote.
_UNPUSHED = BranchObservation(
    repo="syntropic137",
    branch=_BRANCH,
    remote="origin",
    remote_commit=_STARTED_AT,
    remote_commit_at_phase_start=_STARTED_AT,
    unpushed_commits=2,
)


def _failed_phase(observed: tuple[BranchObservation, ...] | None) -> PhaseExecutionDetail:
    return PhaseExecutionDetail(
        workflow_phase_id="implement",
        name="Implement",
        status="failed",
        session_id=None,
        error_message="the phase produced none of its declared output",
        observed_branches=observed,
    )


@pytest.mark.anyio
async def test_a_moved_ref_reaches_the_api_model_with_both_readings() -> None:
    """Hop 1: read model -> PhaseExecution, every field intact.

    Asserted as the whole value rather than field by field, because a hop that
    forwarded the branch and dropped `remote_commit_at_phase_start` would leave
    a client with a SHA and nothing to compare it against - which is the
    attribution again, stated as a bare fact about a commit.
    """
    mapped = await _map_phase_detail(_failed_phase((_MOVED,)), None, {})

    assert mapped.observed_branches == [
        BranchObservationInfo(
            repo="syntropic137",
            branch=_BRANCH,
            remote="origin",
            remote_commit=_NOW,
            remote_commit_at_phase_start=_STARTED_AT,
            unpushed_commits=0,
        )
    ]


@pytest.mark.anyio
async def test_a_moved_ref_reaches_the_http_response() -> None:
    """Hop 2: PhaseExecution -> PhaseExecutionInfo, which is what is served."""
    phase = PhaseExecution(
        phase_id="implement",
        name="Implement",
        status="failed",
        observed_branches=[
            BranchObservationInfo(
                repo="syntropic137",
                branch=_BRANCH,
                remote="origin",
                remote_commit=_NOW,
                remote_commit_at_phase_start=_STARTED_AT,
                unpushed_commits=0,
            )
        ],
    )

    response = _map_phase_to_response(phase)

    assert response.observed_branches is not None
    assert [
        (w.branch, w.remote_commit, w.remote_commit_at_phase_start)
        for w in response.observed_branches
    ] == [(_BRANCH, _NOW, _STARTED_AT)]


@pytest.mark.anyio
async def test_unpushed_commits_survive_as_a_count_not_a_flag() -> None:
    """The count is what tells a client the branch is not worth fetching.

    A ref that has not moved and a workspace holding two commits no remote has
    are the same branch name and the same SHA; only `unpushed_commits`
    separates "there is nothing here" from "there is work here that dies with
    the container". A hop that forwarded the SHAs and dropped the count would
    serve the first sentence for the second situation.
    """
    mapped = await _map_phase_detail(_failed_phase((_UNPUSHED,)), None, {})

    assert mapped.observed_branches is not None
    (record,) = mapped.observed_branches
    assert record.unpushed_commits == 2
    assert record.remote_commit == record.remote_commit_at_phase_start

    (served,) = _map_phase_to_response(mapped).observed_branches or ()
    assert served.unpushed_commits == 2


@pytest.mark.anyio
async def test_the_four_states_stay_four_values_at_the_boundary() -> None:
    """The distinction the whole feature is for, made where a client reads it.

    A moved ref: fetch it. Commits on no remote: nothing to fetch, and #1184
    is quarantining them. Empty list: git was read and nothing differs from how
    the phase found it. Null: the workspace could not answer, so work MAY be
    out there and a human should go and check.

    The middle two are the pair that used to collapse - both ended with nothing
    of this phase's on a remote, and both served `[]`. They are asserted
    UNEQUAL rather than each equal to their own value, because two constants
    can drift back into agreement while both single-case assertions still pass.
    """
    served = {
        case: _map_phase_to_response(await _map_phase_detail(_failed_phase(observed), None, {}))
        for case, observed in (
            ("ref moved", (_MOVED,)),
            ("committed, unpushed", (_UNPUSHED,)),
            ("nothing differs", ()),
            ("nobody could look", None),
        )
    }

    assert served["nothing differs"].observed_branches == []
    assert served["nobody could look"].observed_branches is None
    assert (
        served["committed, unpushed"].observed_branches
        != served["nothing differs"].observed_branches
    ), "a client cannot tell doomed commits from an untouched workspace"
    assert len({repr(response.observed_branches) for response in served.values()}) == 4, (
        f"four incidents must be four served values: {served}"
    )


@pytest.mark.anyio
async def test_a_phase_that_did_not_fail_carries_nothing() -> None:
    """(e) at this layer: the success path is untouched and stays null."""
    completed = PhaseExecutionDetail(
        workflow_phase_id="implement",
        name="Implement",
        status="completed",
        session_id=None,
    )

    mapped = await _map_phase_detail(completed, None, {})

    assert mapped.observed_branches is None
    assert _map_phase_to_response(mapped).observed_branches is None
