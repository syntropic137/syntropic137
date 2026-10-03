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
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import PhaseUsage
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

#: A 124 raised seven minutes into an hour-long budget. Same exit code, and
#: nowhere near the cap - so it is not a timeout at all, it is something else
#: wearing a timeout's exit code, and "raise the budget" is the wrong answer
#: to it. 431 is not a round number and cannot be arrived at by defaulting.
DIED_EARLY_AT = PHASE_STARTED_AT + timedelta(seconds=431)

#: What the overnight run had spent when it was killed: 735 tokens, against a
#: budget measured in hours. The activity summary says the same thing about the
#: same phase from the other side - four calls, no push - and the two readings
#: are independent, which is what makes either one worth having.
STALLED_SPEND = PhaseUsage(
    input_tokens=190,
    output_tokens=545,
    cache_creation_tokens=13,
    cache_read_tokens=27,
)

#: What the runs that genuinely needed a bigger cap had spent. Orders of
#: magnitude away from the above, because that distance is the point.
BUSY_SPEND = PhaseUsage(
    input_tokens=180_400,
    output_tokens=94_100,
    cache_creation_tokens=22_000,
    cache_read_tokens=1_400_000,
)


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

    def __init__(self, operations: list[ToolOperation] | None, *, raises: bool = False) -> None:
        self.session_tools = _SessionTools(operations, raises=raises)


class _SessionTools:
    """One session's timeline, answering the way the real projection answers.

    THREE-VALUED on purpose, because that is what is under test: rows, `[]` for
    a session that recorded none, and `None` for a timeline that could not be
    read - the projection's answer when it has no pool. `raises` is the other
    way a reader finds out it cannot see, and the phase mapper has to arrive at
    the same place from both.
    """

    def __init__(self, operations: list[ToolOperation] | None, *, raises: bool = False) -> None:
        self._operations = operations
        self._raises = raises

    async def get(self, session_id: str) -> list[ToolOperation] | None:
        assert session_id == SESSION_ID
        if self._raises:
            raise RuntimeError("connection reset by peer while reading the timeline")
        return self._operations


async def _phase_as_an_api_client_sees_it(
    operations: list[ToolOperation] | None,
    *,
    budgeted: bool = True,
    spent: PhaseUsage | None = None,
    telemetry_raises: bool = False,
    died_at: datetime = PHASE_DIED_AT,
    session_id: str | None = SESSION_ID,
) -> PhaseExecutionInfo:
    """Drive a timed-out phase from its events to the served response model.

    The run starts (stating its phase budgets), the phase starts, and then the
    workflow FAILS with the phase named - which is the path a timeout takes.
    There is no PhaseCompleted, so anything only written at a clean teardown is
    absent by construction, exactly as it is for a real exit 124.

    `budgeted=False` is the execution started without phase definitions, where
    no budget was ever stated. `spent` is what the phase had burned when it was
    killed; absent, it is the zeros a run that spent nothing reports.

    `operations=None` is the timeline answering "I could not read this", and
    `telemetry_raises=True` is the lookup dying outright; both are Lane 2
    being unavailable, arrived at by the two routes that reach it. `died_at`
    moves the kill, so a 124 can be put inside the budget as well as past it.
    `session_id=None` is the phase that never got a session at all, which has
    no timeline to read by construction.
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
            "session_id": session_id,
            "started_at": PHASE_STARTED_AT.isoformat(),
        }
    )
    await projection.on_workflow_failed(
        {
            "execution_id": EXECUTION_ID,
            "workflow_id": "wf-1262",
            "failed_at": died_at.isoformat(),
            "failed_phase_id": PHASE_ID,
            "error_message": "Agent process exited with code 124",
            "failed_phase_duration_seconds": (died_at - PHASE_STARTED_AT).total_seconds(),
            "failed_phase_input_tokens": (spent or PhaseUsage()).input_tokens,
            "failed_phase_output_tokens": (spent or PhaseUsage()).output_tokens,
            "failed_phase_cache_creation_tokens": (spent or PhaseUsage()).cache_creation_tokens,
            "failed_phase_cache_read_tokens": (spent or PhaseUsage()).cache_read_tokens,
        }
    )

    record = await store.get(WorkflowExecutionDetailProjection.PROJECTION_NAME, EXECUTION_ID)
    assert record is not None, "the projection must have stored the execution"
    detail = WorkflowExecutionDetail.from_dict(record)
    mapped = await _map_phase_detail(
        detail.phases[0],
        _Timeline(operations, raises=telemetry_raises),  # pyright: ignore[reportArgumentType]
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
async def test_what_a_timed_out_phase_spent_reaches_the_client() -> None:
    """The counts an operator sorts on, read off the model a client receives.

    These were zero for every failed phase until #1262, because only
    `PhaseCompleted` ever wrote them and a phase killed at its timeout never
    gets one. The cache pair is asserted with the rest because it does not take
    the same route: `_map_phase_detail` prefers Lane 2 session cost for those
    two and falls back to the phase's own, so they can be lost at a hop the
    input and output counts never touch.
    """
    phase = await _phase_as_an_api_client_sees_it(_stalled_timeline(), spent=STALLED_SPEND)

    assert phase.input_tokens == 190
    assert phase.output_tokens == 545
    assert phase.cache_creation_tokens == 13
    assert phase.cache_read_tokens == 27
    assert phase.total_tokens == 775, "the four summed, not one of them alone"


@pytest.mark.anyio
async def test_the_two_exit_124s_cost_visibly_different_amounts() -> None:
    """735 tokens and 1.7 million, on the same exit code and the same budget.

    The price is the second independent reading of the same distinction the
    activity summary makes, and the one that answers "was this worth paying
    again". A phase that reported zero either way answered nothing.
    """
    stalled = await _phase_as_an_api_client_sees_it(_stalled_timeline(), spent=STALLED_SPEND)
    busy = await _phase_as_an_api_client_sees_it(_busy_timeline(), spent=BUSY_SPEND)

    assert stalled.total_tokens == 775
    assert busy.total_tokens == 1_696_500
    assert stalled.total_tokens != busy.total_tokens


@pytest.mark.anyio
async def test_a_phase_that_spent_nothing_reports_zero_rather_than_nothing() -> None:
    """Zero is a measurement here, and the field is present to carry it.

    A phase whose process never got anywhere did spend nothing, and that is a
    triage answer in its own right - it says the failure is upstream of the
    agent. Which is also why none of these fields is nullable: there is no
    "unknown" for a reader to have to interpret.
    """
    phase = await _phase_as_an_api_client_sees_it(_stalled_timeline())

    assert phase.input_tokens == 0
    assert phase.total_tokens == 0
    assert phase.activity.operations_count == 4, "the other readings are unaffected"


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


# -- "we could not see" is a third answer, not a quiet stall ------------------
#
# The pair below is the whole guard, and neither test means anything alone.
# Both end with an empty timeline in hand; they differ only in WHY it is empty,
# and that difference is the one an operator's decision turns on. A single test
# cannot distinguish them, which is how the collapse survived review: every
# assertion about a broken lookup was also true of a phase that did nothing.


@pytest.mark.anyio
async def test_a_timeline_that_could_not_be_read_reports_no_readings_at_all() -> None:
    """A dead telemetry query must not arrive as a phase that sat idle.

    This is the defect the feature was manufacturing against itself. The
    lookup raises - a reset connection, a dropped pool - the read path fails
    soft as Lane 2 should, and what reached the client was `operations_count:
    0` and `last_push_at: null`: the stall reading, which is the one that
    tells an operator to stop paying for the run. Invented from an outage,
    about a phase nobody looked at.

    `operations_count` is asserted to be None rather than merely "not 4",
    because 0 is a real answer here and the point is that this is not one.
    """
    phase = await _phase_as_an_api_client_sees_it(None, telemetry_raises=True)

    assert phase.activity.telemetry_available is False
    assert phase.activity.operations_count is None, "0 would be a measurement nobody took"
    assert phase.activity.last_push_at is None


@pytest.mark.anyio
async def test_a_timeline_read_and_genuinely_empty_still_reports_zero() -> None:
    """The other half: zero is a real reading and must survive the fix.

    A phase whose process never got anywhere made no calls and pushed nothing,
    and saying so is a triage answer in its own right - it puts the failure
    upstream of the agent. A fix that answered "unknown" whenever the list was
    empty would have destroyed this reading while claiming to protect it, and
    every assertion here is in the non-default direction: `telemetry_available`
    defaults to False and `operations_count` to None.
    """
    phase = await _phase_as_an_api_client_sees_it([])

    assert phase.activity.telemetry_available is True
    assert phase.activity.operations_count == 0
    assert phase.activity.last_push_at is None


@pytest.mark.anyio
async def test_an_unreadable_timeline_and_an_empty_one_are_two_served_answers() -> None:
    """The pair, stated as the inequality the two tests above cannot state.

    Two absolute assertions can drift back into agreement while both still
    pass, and agreement here IS the defect: one response, two incidents, no
    way to tell which one is in front of you. Asserted on the served model,
    because the distinction is worth nothing if it dies at a hop.
    """
    unreadable = (await _phase_as_an_api_client_sees_it(None, telemetry_raises=True)).activity
    genuinely_empty = (await _phase_as_an_api_client_sees_it([])).activity

    assert unreadable.elapsed_seconds == genuinely_empty.elapsed_seconds, (
        "fixture: both phases died at the same instant, so elapsed cannot separate them"
    )
    assert unreadable != genuinely_empty, (
        "a telemetry outage and an idle phase must not read identically"
    )


@pytest.mark.anyio
async def test_a_projection_that_answers_none_is_read_as_unavailable_too() -> None:
    """The no-pool route to the same place, as the projection renders it.

    `SessionToolsProjection.get` returns None rather than raising when there is
    no database to ask - the test-and-offline case, and the production case
    while the pool is still coming up. It is the same "we could not see" as a
    dead query and has to survive the same five hops, so it is asserted at the
    same place: the response model.
    """
    phase = await _phase_as_an_api_client_sees_it(None)

    assert phase.activity.telemetry_available is False
    assert phase.activity.operations_count is None


@pytest.mark.anyio
async def test_a_phase_that_never_got_a_session_claims_nothing_about_its_work() -> None:
    """No session id is no timeline, which is again "we could not see".

    A phase that died before it was handed a session has nothing recorded
    against it by construction. Reporting that as zero operations is the same
    false stall as an unreachable query, reached without any query at all -
    and it is the more common of the two, because it needs no outage.
    """
    phase = await _phase_as_an_api_client_sees_it([], session_id=None)

    assert phase.session_id is None, "fixture: the phase never got a session"
    assert phase.activity.telemetry_available is False
    assert phase.activity.operations_count is None


@pytest.mark.anyio
async def test_an_unreadable_timeline_still_says_whether_the_cap_was_reached() -> None:
    """What is withheld is busy-versus-stalled, and only that.

    `elapsed_seconds` and `timeout_seconds` come from the execution record, not
    from Lane 2, so a telemetry outage says nothing about them and must not
    take them down with it. A phase with an unreadable timeline is still
    triageable against its budget - which is the difference between a degraded
    reading and a useless one.
    """
    activity = (await _phase_as_an_api_client_sees_it(None, telemetry_raises=True)).activity

    assert activity.timeout_seconds == BUDGET_SECONDS
    assert activity.elapsed_seconds == float(BUDGET_SECONDS + 21)


# -- the cap, and the 124 that is not the cap --------------------------------


@pytest.mark.anyio
async def test_a_124_well_inside_the_budget_reads_as_one() -> None:
    """The counterexample to "reached its cap", which needs a third response.

    `test_reaching_the_cap_is_legible_against_the_budget` above shows a phase
    dying past its deadline. On its own that proves only that two numbers were
    served; it cannot show they mean anything, because a hop that reported the
    elapsed time as the budget, or the budget as the elapsed time, would still
    satisfy it. This one dies at 431 seconds against 3600 - the comparison
    lands the other way round, and neither number can be standing in for the
    other.

    An operator reading this does not raise the budget: 124 seven minutes into
    an hour is a process that was killed by something else, and a bigger cap
    buys nothing.
    """
    phase = await _phase_as_an_api_client_sees_it(_stalled_timeline(), died_at=DIED_EARLY_AT)
    activity = phase.activity

    assert activity.elapsed_seconds == 431.0, "the measured life of the phase, to the client"
    assert activity.timeout_seconds == BUDGET_SECONDS, "the budget it did NOT reach"
    assert activity.elapsed_seconds < activity.timeout_seconds
    assert phase.duration_seconds == 431.0, (
        "the phase's own duration and the activity's elapsed are one measurement"
    )


@pytest.mark.anyio
async def test_the_two_124s_land_on_opposite_sides_of_the_same_budget() -> None:
    """At the cap and nowhere near it, told apart by the pair of readings.

    Same exit code, same budget, and the only thing separating them is where
    elapsed falls against timeout. Asserted as a comparison rather than as two
    constants, because two constants that both drifted would keep passing.
    """
    at_the_cap = (await _phase_as_an_api_client_sees_it(_busy_timeline())).activity
    well_inside = (
        await _phase_as_an_api_client_sees_it(_stalled_timeline(), died_at=DIED_EARLY_AT)
    ).activity

    assert at_the_cap.timeout_seconds == well_inside.timeout_seconds == BUDGET_SECONDS
    assert at_the_cap.elapsed_seconds is not None
    assert well_inside.elapsed_seconds is not None
    assert at_the_cap.elapsed_seconds > BUDGET_SECONDS > well_inside.elapsed_seconds
