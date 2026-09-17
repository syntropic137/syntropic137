"""An operator can tell a timed-out phase from a stalled one (#1262).

Both exit 124. The responses are opposite - give the busy phase a bigger budget
and dispatch a continuation, do not pay for the stalled one again - and until
`phases[].activity` existed the execution record said nothing that separated
them. Four runs in one day were triaged from transcripts; two survived only
because the agent happened to push as it went.

WHY EVERY TEST HERE ENDS AT THE RESPONSE MODEL. There are five hops between the
recorded fact and the HTTP response - projection, stored dict,
`PhaseExecutionDetail`, `PhaseExecution`, `PhaseExecutionInfo` - and each one
re-lists its fields by hand. This repository has dropped a field at exactly such
a hop three times (#891, #1176, #1300), and asserting on either end catches
none of them. So a fact is put in where the system records it and read out of
the model an API client receives.

WHAT THE FIXTURES ARE. The busy phase is the shape of the runs that were
misjudged: hundreds of calls and a push moments before the kill. The stalled one
is four calls and no push for most of an hour. Neither's numbers can arise from
a default - `operations_count` defaults to 0 and every other field to None - so
a hop that drops one fails rather than coincidentally agreeing.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore
from syn_adapters.projections.session_tools import ToolOperation
from syn_api.routes.executions.phase_mapping import _map_phase_detail, _map_phase_to_response
from syn_domain.contexts.orchestration.domain.read_models.workflow_execution_detail import (
    WorkflowExecutionDetail,
)
from syn_domain.contexts.orchestration.slices.get_execution_detail.projection import (
    WorkflowExecutionDetailProjection,
)

if TYPE_CHECKING:
    from syn_api.routes.executions.models import PhaseExecutionInfo

pytestmark = pytest.mark.unit

EXECUTION_ID = "exec-1262"
PHASE_ID = "phase-implement"
SESSION_ID = "sess-1262"

#: The budget the phase was given. 3600s is the real cap these runs die on.
BUDGET_SECONDS = 3600

PHASE_STARTED_AT = datetime(2026, 9, 17, 10, 0, 0, tzinfo=UTC)
#: The kill: past the cap by the ~20s of teardown a real timeout overshoots by.
PHASE_DIED_AT = PHASE_STARTED_AT + timedelta(seconds=BUDGET_SECONDS + 21)

#: "Pushed 90 seconds before dying" - the reading that says it was working.
PUSHED_AT = PHASE_DIED_AT - timedelta(seconds=90)


def _call(index: int, *, at: datetime) -> list[ToolOperation]:
    """The TWO timeline rows one tool call leaves behind.

    Returned as a pair on purpose: the list an API client receives is rows, and
    `operations_count` has to be calls. A helper that produced one row per call
    would make the double-count (#1061) untestable.
    """
    return [
        ToolOperation(
            observation_id=f"obs-{index}-{kind}",
            tool_name="Bash",
            tool_use_id=f"toolu_{index}",
            operation_type=f"tool_execution_{kind}",
            timestamp=at,
            success=None if kind == "started" else True,
            input_preview=None,
            output_preview=None,
            duration_ms=None,
        )
        for kind in ("started", "completed")
    ]


def _push(at: datetime, *, operation_type: str = "git_push") -> ToolOperation:
    """A push as the timeline records it: no `tool_use_id`, by construction."""
    return ToolOperation(
        observation_id=f"obs-push-{at.isoformat()}",
        tool_name="push",
        tool_use_id=None,
        operation_type=operation_type,
        timestamp=at,
        success=True,
        input_preview=None,
        output_preview=None,
        duration_ms=None,
    )


class _Timeline:
    """A projection manager carrying one session's timeline and nothing else.

    The cost lookup in `_map_phase_detail` is guarded and falls back, which is
    what this wants: the subject is the activity summary, not Lane 2 cost.
    """

    def __init__(self, operations: list[ToolOperation]) -> None:
        self.session_tools = _SessionTools(operations)


class _SessionTools:
    def __init__(self, operations: list[ToolOperation]) -> None:
        self._operations = operations

    async def get(self, session_id: str) -> list[ToolOperation]:
        assert session_id == SESSION_ID
        return self._operations


async def _phase_as_an_api_client_sees_it(
    operations: list[ToolOperation],
    *,
    budgeted: bool = True,
) -> PhaseExecutionInfo:
    """Drive a timed-out phase from its events to the served response model.

    The run starts (stating its phase budgets), the phase starts, and then the
    workflow FAILS with the phase named - which is the path a timeout takes.
    There is no PhaseCompleted, so anything only written at a clean teardown is
    absent by construction, exactly as it is for a real exit 124.

    `budgeted=False` is the execution started without phase definitions, where
    no budget was ever stated.
    """
    store = InMemoryProjectionStore()
    projection = WorkflowExecutionDetailProjection(store)

    await projection.on_workflow_execution_started(
        {
            "execution_id": EXECUTION_ID,
            "workflow_id": "wf-1262",
            "workflow_name": "sdlc-implement",
            "started_at": PHASE_STARTED_AT.isoformat(),
            "total_phases": 1,
            "phase_definitions": (
                [
                    {
                        "phase_id": PHASE_ID,
                        "name": "implement",
                        "order": 0,
                        "timeout_seconds": BUDGET_SECONDS,
                    }
                ]
                if budgeted
                else None
            ),
        }
    )
    await projection.on_phase_started(
        {
            "execution_id": EXECUTION_ID,
            "phase_id": PHASE_ID,
            "phase_name": "implement",
            "session_id": SESSION_ID,
            "started_at": PHASE_STARTED_AT.isoformat(),
        }
    )
    await projection.on_workflow_failed(
        {
            "execution_id": EXECUTION_ID,
            "workflow_id": "wf-1262",
            "failed_at": PHASE_DIED_AT.isoformat(),
            "failed_phase_id": PHASE_ID,
            "error_message": "Agent process exited with code 124",
            "failed_phase_duration_seconds": (PHASE_DIED_AT - PHASE_STARTED_AT).total_seconds(),
        }
    )

    record = await store.get(WorkflowExecutionDetailProjection.PROJECTION_NAME, EXECUTION_ID)
    assert record is not None, "the projection must have stored the execution"
    detail = WorkflowExecutionDetail.from_dict(record)
    mapped = await _map_phase_detail(
        detail.phases[0],
        _Timeline(operations),  # pyright: ignore[reportArgumentType]
        {},
    )
    return _map_phase_to_response(mapped)


def _busy_timeline() -> list[ToolOperation]:
    """300 calls and a push 90 seconds before the kill. This one was working."""
    operations: list[ToolOperation] = []
    for index in range(300):
        operations.extend(_call(index, at=PHASE_STARTED_AT + timedelta(seconds=index * 10)))
    operations.append(_push(PUSHED_AT))
    return operations


def _stalled_timeline() -> list[ToolOperation]:
    """Four calls, then forty minutes of nothing. Nothing was pushed, ever."""
    return [
        row
        for index in range(4)
        for row in _call(index, at=PHASE_STARTED_AT + timedelta(seconds=index * 5))
    ]


@pytest.mark.anyio
async def test_a_busy_phase_reports_its_work_and_its_last_push() -> None:
    """The run that needs a bigger budget, as the response describes it.

    601 rows become 301 operations: 300 tool calls, each a start row and a
    completion row folded back into one, plus the push, which is a single row
    and an operation in its own right. Counting rows would answer 601 - the
    #1061 double-count arriving in a new field, and "made 601 tool calls in an
    hour" is a different triage decision from "made 301".
    """
    phase = await _phase_as_an_api_client_sees_it(_busy_timeline())

    assert len(phase.operations) == 601, "fixture: 300 calls as rows, plus the push"
    assert phase.activity.operations_count == 301
    assert phase.activity.last_push_at == PUSHED_AT
    assert phase.activity.seconds_since_last_push == 90.0


@pytest.mark.anyio
async def test_a_stalled_phase_reports_four_calls_and_no_push_at_all() -> None:
    """The run not to pay for again, and the null that is the loudest signal.

    `last_push_at` is None because nothing was pushed - which also says the
    phase's work died with the container. `seconds_since_last_push` is None
    rather than a number because there is no push to measure from; the silence
    is the whole phase, and `elapsed_seconds` already reports that.
    """
    phase = await _phase_as_an_api_client_sees_it(_stalled_timeline())

    assert phase.activity.operations_count == 4
    assert phase.activity.last_push_at is None
    assert phase.activity.seconds_since_last_push is None
    assert phase.activity.elapsed_seconds == float(BUDGET_SECONDS + 21)


@pytest.mark.anyio
async def test_the_two_exit_124s_are_two_different_served_answers() -> None:
    """The distinction the whole change is for, where a client reads it.

    Asserted as "these differ", not only as two absolute values: two constants
    can drift back into agreement while both single-case assertions still pass,
    and agreement here is precisely the defect - one exit code, one record, no
    way to choose a response.
    """
    busy = (await _phase_as_an_api_client_sees_it(_busy_timeline())).activity
    stalled = (await _phase_as_an_api_client_sees_it(_stalled_timeline())).activity

    assert busy.timeout_seconds == stalled.timeout_seconds == BUDGET_SECONDS
    assert busy.elapsed_seconds == stalled.elapsed_seconds, (
        "fixture: both died at the same instant, so elapsed cannot be what separates them"
    )
    assert busy != stalled, "two incidents that need opposite responses read identically"


@pytest.mark.anyio
async def test_reaching_the_cap_is_legible_against_the_budget() -> None:
    """ "Hit the cap" versus "reported 124 early", which need different answers.

    The budget is the half that was missing: an elapsed time alone cannot say
    whether a run reached its deadline, and a client cannot supply the number
    because it is stated once, at the start of the run, on an event no read
    surface exposed. Both readings are asserted, because either one alone is
    the same ambiguity in a new place.
    """
    at_the_cap = (await _phase_as_an_api_client_sees_it(_busy_timeline())).activity

    assert at_the_cap.timeout_seconds == BUDGET_SECONDS
    assert at_the_cap.elapsed_seconds is not None
    assert at_the_cap.elapsed_seconds > BUDGET_SECONDS, (
        "a phase killed on its deadline overshoots it by its teardown"
    )


@pytest.mark.anyio
async def test_a_run_that_stated_no_budget_says_so_rather_than_guessing() -> None:
    """Null is "nobody stated one", and it must not become a number.

    A default here - 300, say, from `PhaseDefinition` - would tell an operator
    that a 3600s phase blew a five-minute cap. The other readings still work,
    so the phase is not silent, it is only missing the one thing nothing knows.
    """
    phase = await _phase_as_an_api_client_sees_it(_busy_timeline(), budgeted=False)

    assert phase.activity.timeout_seconds is None
    assert phase.activity.operations_count == 301, "the other readings are unaffected"


@pytest.mark.anyio
async def test_a_push_recorded_under_a_legacy_name_is_still_a_push() -> None:
    """`git_push_completed` is a push, and answering "none" would read as a stall.

    The collector keeps the legacy hook spellings for rows already in the
    database and its parser still maps them, so a session's timeline can hand
    the summary either. Wrong in this direction is expensive: no push observed
    is the reading that says stop paying for the run.
    """
    timeline = _stalled_timeline()
    timeline.append(_push(PUSHED_AT, operation_type="git_push_completed"))

    phase = await _phase_as_an_api_client_sees_it(timeline)

    assert phase.activity.last_push_at == PUSHED_AT
    assert phase.activity.seconds_since_last_push == 90.0


@pytest.mark.anyio
async def test_a_running_phase_measures_its_silence_against_now() -> None:
    """A live phase's silence grows; a dead one's is frozen at the kill.

    The same rule `duration_seconds` follows, so the two numbers cannot
    disagree about where the phase ended. Without it a phase that has been
    silent for an hour reports the gap it had at some earlier read - which is
    the frozen-duration misreading that got six healthy runs cancelled.
    """
    store = InMemoryProjectionStore()
    projection = WorkflowExecutionDetailProjection(store)
    await projection.on_workflow_execution_started(
        {
            "execution_id": EXECUTION_ID,
            "workflow_id": "wf-1262",
            "workflow_name": "sdlc-implement",
            "started_at": PHASE_STARTED_AT.isoformat(),
            "total_phases": 1,
            "phase_definitions": [
                {
                    "phase_id": PHASE_ID,
                    "name": "implement",
                    "order": 0,
                    "timeout_seconds": BUDGET_SECONDS,
                }
            ],
        }
    )
    await projection.on_phase_started(
        {
            "execution_id": EXECUTION_ID,
            "phase_id": PHASE_ID,
            "phase_name": "implement",
            "session_id": SESSION_ID,
            "started_at": PHASE_STARTED_AT.isoformat(),
        }
    )

    record = await store.get(WorkflowExecutionDetailProjection.PROJECTION_NAME, EXECUTION_ID)
    assert record is not None
    detail = WorkflowExecutionDetail.from_dict(record)
    assert detail.phases[0].status == "running"

    mapped = await _map_phase_detail(
        detail.phases[0],
        _Timeline([_push(PUSHED_AT)]),  # pyright: ignore[reportArgumentType]
        {},
    )
    activity = _map_phase_to_response(mapped).activity

    assert activity.timeout_seconds == BUDGET_SECONDS
    assert activity.seconds_since_last_push is not None
    assert activity.seconds_since_last_push > 90.0, (
        "a running phase measures to now, so its silence exceeds the gap to its kill"
    )


@pytest.mark.anyio
async def test_the_budget_survives_a_completion_whose_start_never_landed() -> None:
    """The projection's other branch carries the budget too.

    `on_phase_completed` builds a record from scratch when PhaseStarted never
    arrived - a truncated replay, a projection rebuilt after the start aged
    out. A fix covering only the update branch would report an unknown budget
    for exactly the runs whose history is already thin (#1300's lesson).
    """
    store = InMemoryProjectionStore()
    projection = WorkflowExecutionDetailProjection(store)
    await projection.on_workflow_execution_started(
        {
            "execution_id": EXECUTION_ID,
            "workflow_id": "wf-1262",
            "workflow_name": "sdlc-implement",
            "started_at": PHASE_STARTED_AT.isoformat(),
            "total_phases": 1,
            "phase_definitions": [
                {
                    "phase_id": PHASE_ID,
                    "name": "implement",
                    "order": 0,
                    "timeout_seconds": BUDGET_SECONDS,
                }
            ],
        }
    )
    await projection.on_phase_completed(
        {
            "execution_id": EXECUTION_ID,
            "phase_id": PHASE_ID,
            "session_id": SESSION_ID,
            "completed_at": PHASE_DIED_AT.isoformat(),
            "duration_seconds": 3621.0,
        }
    )

    record = await store.get(WorkflowExecutionDetailProjection.PROJECTION_NAME, EXECUTION_ID)
    assert record is not None
    detail = WorkflowExecutionDetail.from_dict(record)
    mapped = await _map_phase_detail(
        detail.phases[0],
        _Timeline([]),  # pyright: ignore[reportArgumentType]
        {},
    )

    assert _map_phase_to_response(mapped).activity.timeout_seconds == BUDGET_SECONDS
