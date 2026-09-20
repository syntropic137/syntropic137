"""#1357: a correct refusal and a platform crash must not read as one number.

Both end a run with `status="failed"`, and until this field existed that was
everything the record said. So every failure rate computed off the domain -
the retrospective workflow's own `classify` phase included - counted the
quality gate WORKING as the platform breaking, and there was nothing in the
event, the read model or the API response to recompute it from.

THE PINNING TEST IS `TestTwoFailuresThatMustNotReadAlike`. Two executions, one
killed by a platform error with no agent report at all and one failed on its
agent's own `TASK_RESULT success=false`, driven through the SAME chain and
asked whether they carry the same classification. They must not.

#1372 ADDED THE THIRD RUN, and it is the one this chain could not previously
tell from the second at all. A phase whose agent reported failure AND named
`"failure_reason": "task"` is not the quality gate working - it is a request
that cannot be done - and until the reason key existed both arrived at the API
as `correct_refusal`. `TestATaskFailureIsNotARefusal` drives it down the same
ten hops and asks the two endpoints to separate them.

The chain is real at every hop, because the defect this guards against is not
in any one of them - it is a value that survives nine hops and is dropped at
the tenth by a constructor that does not pass it:

    the agent's text  ->  VerdictReader  ->  AgentVerdict
      ->  PhaseReportedFailureError    (the only frame that still knows)
      ->  failed_phase_outcome         ->  PhaseFailure
      ->  FailExecutionCommand         ->  WorkflowExecutionAggregate
      ->  WorkflowFailedEvent          ->  the list + detail projections
      ->  WorkflowExecutionSummary / ...Detail
      ->  ExecutionSummaryResponse / ExecutionDetailResponse

Nothing here is hand-written at an intermediate hop: each stage is fed the
previous stage's real output, so a hop that forgets the field fails these
rather than being papered over by a fixture that already knows the answer.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from event_sourcing import GenericDomainEvent

from syn_adapters.projection_stores import InMemoryProjectionStore
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    FailureClassification,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
    StartExecutionCommand,
    WorkflowExecutionAggregate,
)
from syn_domain.contexts.orchestration.domain.events.WorkflowExecutionStartedEvent import (
    WorkflowExecutionStartedEvent,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.errors import (
    PhaseReportedFailureError,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.phase_outcome import (
    failed_phase_outcome,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.phase_verdict import VerdictReader
from syn_domain.contexts.orchestration.slices.get_execution_detail.projection import (
    WorkflowExecutionDetailProjection,
)
from syn_domain.contexts.orchestration.slices.list_executions.projection import (
    WorkflowExecutionListProjection,
)

if TYPE_CHECKING:
    from syn_api.routes.executions.models import (
        ExecutionDetailResponse,
        ExecutionSummaryResponse,
    )
    from syn_domain.contexts.orchestration.domain.events.WorkflowFailedEvent import (
        WorkflowFailedEvent,
    )

pytestmark = pytest.mark.unit

#: The run whose agent said, in the words the prompt asks for, that it would
#: not do the task. The platform recorded that faithfully: the system WORKING.
REFUSED_ID = "exec-refused-1357"
#: The run whose container died with the agent never having reported anything.
CRASHED_ID = "exec-crashed-1357"
#: The run whose agent reported failure and named the REQUEST as its cause
#: (#1372): not an outage, and not the gate working either - a brief that has
#: to be rewritten before any rerun can do better.
TASK_ID = "exec-task-1372"
#: The run that ended BEFORE this field existed. Neither its events nor the row
#: the projection wrote for it carry the key at all, and no VERSION bump means
#: that row is never rebuilt - so this is what the store actually holds for the
#: 221 failures the issue counted.
HISTORICAL_ID = "exec-historical-1357"

#: A classification no reader here knows, standing in for a newer writer's
#: member or a corrupted row. Deliberately unspellable as a real one.
_NEVER_A_MEMBER = "recorded-by-a-version-that-does-not-exist-yet"

WORKFLOW_ID = "wf-1357"
PHASE_ID = "implement"
TOTAL_PHASES = 3

_STARTED_AT = datetime(2026, 9, 18, 9, 0, tzinfo=UTC)
_FAILED_AT = datetime(2026, 9, 18, 9, 40, tzinfo=UTC)

#: What the refusing agent actually wrote, terminator and all, as its phase's
#: stream delivered it. Read rather than asserted: `VerdictReader` is the thing
#: that decides this text is a refusal, and a test that skipped it would be
#: pinning its own opinion of the text instead of the platform's.
_REFUSAL_MESSAGES = (
    "The premise is false: the module the issue names was deleted in #1201.",
    'TASK_RESULT: {"success": false, "comments": "premise false, refusing to '
    'invent a fix"}\nTASK_RESULT_END',
    "Stopping here rather than guessing.",
)

#: A marker with nothing readable under it. It refuses completion for the same
#: reason a real refusal does, and it is NOT evidence the platform worked.
_UNREADABLE_MESSAGES = ("TASK_RESULT: {success: probably not",)

#: What an agent handed an impossible brief writes (#1372), in the shape the
#: prompt hands it. The `failure_reason` is the ONLY difference from
#: `_REFUSAL_MESSAGES` - same `success=false`, same prose, same terminator -
#: which is the point: nothing else in these bytes could tell the two runs
#: apart, and before the key existed nothing did.
_TASK_MESSAGES = (
    "Issue #9001 names a file this repository has never contained.",
    'TASK_RESULT: {"success": false, "failure_reason": "task", "comments": "the '
    'brief names a module that does not exist; no change can satisfy it"}\nTASK_RESULT_END',
)


def _refusal_error() -> PhaseReportedFailureError:
    """The exception a phase that reported `success=false` dies on."""
    reader = VerdictReader()
    for message in _REFUSAL_MESSAGES:
        reader.read(message)
    return PhaseReportedFailureError(phase_id=PHASE_ID, verdict=reader.verdict)


def _unreadable_error() -> PhaseReportedFailureError:
    """The exception a phase whose report nobody could parse dies on."""
    reader = VerdictReader()
    for message in _UNREADABLE_MESSAGES:
        reader.read(message)
    return PhaseReportedFailureError(phase_id=PHASE_ID, verdict=reader.verdict)


def _task_error() -> PhaseReportedFailureError:
    """The exception a phase that reported an impossible task dies on (#1372).

    Built the same way as `_refusal_error`, through the real reader, so what
    reaches the chain is whatever `VerdictReader` makes of the bytes above -
    not a classification this test chose.
    """
    reader = VerdictReader()
    for message in _TASK_MESSAGES:
        reader.read(message)
    return PhaseReportedFailureError(phase_id=PHASE_ID, verdict=reader.verdict)


def _crash_error() -> BaseException:
    """A platform failure with no agent report anywhere near it."""
    return RuntimeError("workspace container exited 137 before the agent reported")


def _started(execution_id: str) -> WorkflowExecutionStartedEvent:
    return WorkflowExecutionStartedEvent(
        workflow_id=WORKFLOW_ID,
        execution_id=execution_id,
        workflow_name="implement-verify-report",
        started_at=_STARTED_AT,
        total_phases=TOTAL_PHASES,
        inputs={},
    )


def _failed(execution_id: str, error: BaseException) -> WorkflowFailedEvent:
    """The event the REAL aggregate emits for a run that died on `error`.

    Every hop from the exception to the event is the production one: the
    outcome derives the classification from the exception, `as_command` puts it
    on the command, and `fail_execution` puts it on the event. A test that
    constructed `WorkflowFailedEvent` directly would pass with any two of those
    three broken.
    """
    outcome = failed_phase_outcome(
        error,
        phase_id=PHASE_ID,
        started_at_by_phase={PHASE_ID: _STARTED_AT},
        session_id_by_phase={},
        now=_FAILED_AT,
    )
    aggregate = WorkflowExecutionAggregate()
    aggregate.start_execution(
        StartExecutionCommand(
            execution_id=execution_id,
            workflow_id=WORKFLOW_ID,
            workflow_name="implement-verify-report",
            total_phases=TOTAL_PHASES,
            inputs={},
        )
    )
    aggregate.fail_execution(
        outcome.as_command(execution_id, completed_phases=0, total_phases=TOTAL_PHASES)
    )
    event = aggregate.get_uncommitted_events()[-1].event
    assert event.event_type == "WorkflowFailed", event.event_type
    return event


@dataclass
class _StubProjectionManager:
    """The two projections the read path needs, and nothing it only reads soft.

    Cost and tool counts both fail soft in the route, so their absence here
    exercises the same path a Lane 2 outage does - which is deliberate: a
    classification that only survives when Lane 2 is up is not in Lane 1.
    """

    store: InMemoryProjectionStore
    workflow_execution_detail: WorkflowExecutionDetailProjection
    workflow_execution_list: WorkflowExecutionListProjection


async def _projections() -> _StubProjectionManager:
    """Both views, built by replaying both runs' real event streams.

    One store backs both, as one does in production: they occupy different
    projection names, and a test that gave them separate stores could not ask
    what a stored ROW looks like without reaching inside a projection.
    """
    store = InMemoryProjectionStore()
    detail = WorkflowExecutionDetailProjection(store)
    listing = WorkflowExecutionListProjection(store)

    for execution_id, error in (
        (REFUSED_ID, _refusal_error()),
        (CRASHED_ID, _crash_error()),
        (TASK_ID, _task_error()),
    ):
        for projection in (detail, listing):
            await projection.on_workflow_execution_started(_started(execution_id).model_dump())
            await projection.on_workflow_failed(_failed(execution_id, error).model_dump())

    return _StubProjectionManager(
        store=store, workflow_execution_detail=detail, workflow_execution_list=listing
    )


async def _projections_with_a_pre_1357_run() -> _StubProjectionManager:
    """The same two views, plus one run that predates the field entirely.

    Two hops have to be aged, because #1367 bumped no projection VERSION and
    both are consequences of that:

    1. the EVENT, whose payload never had the key - nothing wrote it; and
    2. the stored ROW, which pre-#1367 projection code wrote without the key
       and which, absent a VERSION bump, is never rebuilt from the stream.

    The row is aged by replaying the aged event and then saving the result back
    with the key removed, rather than by hand-writing a row: every other column
    is then exactly what the production projection produces, so this stays a
    real row of that shape as the projection evolves.

    The two live runs are kept alongside deliberately. `UNCLASSIFIED` is the
    DEFAULT on both response models, so a historical run asserted on its own
    would pass just as well against a read path that dropped the field at every
    hop - the neighbours are what tell "resolved to unclassified" apart from
    "never carried at all".
    """
    manager = await _projections()
    store = manager.store
    detail, listing = manager.workflow_execution_detail, manager.workflow_execution_list

    aged = _failed(HISTORICAL_ID, _refusal_error()).model_dump()
    del aged["failure_classification"]

    for projection in (detail, listing):
        await projection.on_workflow_execution_started(_started(HISTORICAL_ID).model_dump())
        await projection.on_workflow_failed(aged)

    for name in (detail.PROJECTION_NAME, listing.PROJECTION_NAME):
        row = await store.get(name, HISTORICAL_ID)
        assert row is not None, f"{name} did not project {HISTORICAL_ID}"
        assert "failure_classification" in row, (
            "the row this test ages no longer carries the key, so removing it "
            "would age nothing and the test would prove nothing"
        )
        await store.save(
            name, HISTORICAL_ID, {k: v for k, v in row.items() if k != "failure_classification"}
        )

    return _StubProjectionManager(
        store=store,
        workflow_execution_detail=detail,
        workflow_execution_list=listing,
    )


def _serve(monkeypatch: pytest.MonkeyPatch, manager: _StubProjectionManager) -> None:
    """Point the route module's lookups at `manager` instead of the real wiring."""
    from syn_api import _wiring
    from syn_api.routes.executions import queries

    async def _noop_connect() -> None:
        return None

    monkeypatch.setattr(queries, "ensure_connected", _noop_connect)
    monkeypatch.setattr(queries, "get_projection_mgr", lambda: manager)
    monkeypatch.setattr(_wiring, "get_projection_mgr", lambda: manager)


async def _detail(monkeypatch: pytest.MonkeyPatch, execution_id: str) -> ExecutionDetailResponse:
    """Serve `GET /executions/{id}` off projections built from real events."""
    from syn_api.routes.executions import queries

    _serve(monkeypatch, await _projections())
    return await queries.get_execution_endpoint(execution_id)


async def _summaries(
    monkeypatch: pytest.MonkeyPatch,
    manager: _StubProjectionManager | None = None,
) -> dict[str, ExecutionSummaryResponse]:
    """Serve `GET /executions`, keyed by execution id.

    `manager` defaults to the two live runs; pass one to serve a different set
    of projections, such as the aged ones in `TestARunOlderThanTheFieldItself`.
    """
    from syn_api.routes.executions import queries

    _serve(monkeypatch, manager if manager is not None else await _projections())
    # Every parameter passed explicitly: called outside FastAPI, the `Query(...)`
    # defaults arrive as `Query` objects rather than as the values they describe.
    response = await queries.list_executions_endpoint(
        status=None,
        statuses=None,
        started_after=None,
        started_before=None,
        q=None,
        page=1,
        page_size=50,
    )
    return {e.workflow_execution_id: e for e in response.executions}


class TestTwoFailuresThatMustNotReadAlike:
    """The test from the issue. Everything else here supports this one."""

    @pytest.mark.asyncio
    async def test_a_crash_and_a_refusal_do_not_carry_the_same_classification(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        refused = await _detail(monkeypatch, REFUSED_ID)
        crashed = await _detail(monkeypatch, CRASHED_ID)

        assert refused.failure_classification != crashed.failure_classification, (
            "a run whose agent reported success=false and a run whose container "
            f"died both report failure_classification="
            f"{refused.failure_classification!r}; every failure number computed "
            "from this record counts the quality gate working as the platform "
            "breaking (#1357)"
        )

    @pytest.mark.asyncio
    async def test_the_refusal_is_named_a_correct_refusal(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Not merely different - named, so a tally can label it.

        `!=` alone would be satisfied by two wrong answers, and the label is
        the whole point: `classify.md` asks for this class to appear in the
        tally WITH its name "so nobody optimises it away".
        """
        refused = await _detail(monkeypatch, REFUSED_ID)

        assert refused.failure_classification is FailureClassification.CORRECT_REFUSAL

    @pytest.mark.asyncio
    async def test_the_crash_is_named_platform(self, monkeypatch: pytest.MonkeyPatch) -> None:
        crashed = await _detail(monkeypatch, CRASHED_ID)

        assert crashed.failure_classification is FailureClassification.PLATFORM

    @pytest.mark.asyncio
    async def test_both_still_report_status_failed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The distinction is BESIDE `status`, never instead of it.

        A refusal did not deliver, and every consumer that treats a failed run
        as terminal - the realtime sentinel, the trigger guards, reconciliation
        - is right to keep treating both alike. Splitting `status` would have
        broken all of them to answer a question none of them asked.
        """
        refused = await _detail(monkeypatch, REFUSED_ID)
        crashed = await _detail(monkeypatch, CRASHED_ID)

        assert (refused.status, crashed.status) == ("failed", "failed")

    @pytest.mark.asyncio
    async def test_the_list_response_separates_them_too(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The other endpoint, off the other projection, on the other model.

        Failure rates get counted over the LIST, not one detail page at a time,
        so a field that reaches only the detail response answers nobody.
        """
        summaries = await _summaries(monkeypatch)

        assert summaries[REFUSED_ID].failure_classification is (
            FailureClassification.CORRECT_REFUSAL
        )
        assert summaries[CRASHED_ID].failure_classification is FailureClassification.PLATFORM


class TestWhatDoubtCountsAs:
    @pytest.mark.asyncio
    async def test_an_unreadable_report_is_not_a_correct_refusal(self) -> None:
        """A block nobody could parse might have been a refusal. Might is not is.

        `refuses_completion` is true for UNREADABLE and for FAILURE alike, so
        the one exception class covers both and classifying off its type would
        collapse them. This is the fail-closed direction: being wrong here
        overstates our own failures, and being wrong the other way credits the
        platform with a refusal nobody can read.
        """
        event = _failed(CRASHED_ID, _unreadable_error())

        assert event.failure_classification is FailureClassification.PLATFORM

    @pytest.mark.asyncio
    async def test_a_failure_recorded_before_1357_replays_as_unclassified(self) -> None:
        """Historical events have no field, and must load rather than guess.

        The payload is a REAL failure event with the key removed, which is
        exactly what the store holds for every run before this change. Both
        readers - the projection that rebuilds the read model and the aggregate
        that rehydrates from the stream - have to answer `unclassified` and
        neither may raise: an event stream that will not replay is worse than a
        number that will not split.
        """
        payload = _failed(REFUSED_ID, _refusal_error()).model_dump()
        del payload["failure_classification"]

        projection = WorkflowExecutionDetailProjection(InMemoryProjectionStore())
        await projection.on_workflow_execution_started(_started(REFUSED_ID).model_dump())
        await projection.on_workflow_failed(payload)
        row = await projection.get_by_id(REFUSED_ID)

        assert row is not None
        assert row.failure_classification is FailureClassification.UNCLASSIFIED
        assert row.status == "failed", "the run still failed; only the KIND is unknown"

        aggregate = WorkflowExecutionAggregate()
        aggregate.on_execution_failed(GenericDomainEvent(**payload))

        assert aggregate.failure_classification is FailureClassification.UNCLASSIFIED

    @pytest.mark.asyncio
    async def test_a_classification_this_reader_does_not_know_replays_as_unclassified(
        self,
    ) -> None:
        """The other direction of the same contract: a NEWER writer.

        A member added later, or a value corrupted in storage, must read as
        unknown rather than raising `ValueError` and stopping the stream. This
        is the reason `from_stored` exists instead of `FailureClassification(...)`
        at each of the read sites.

        The value is asserted NOT to be a member first, and that guard is the
        lesson of #1372 rather than belt-and-braces: this test used to spell it
        `"task"`, which #1372 then made real. The day it did, the test went on
        passing while asserting the opposite of what it says - a known member
        reading as unclassified would be a defect, not the contract. So the
        input is pinned to be unknown rather than trusted to stay that way.
        """
        assert _NEVER_A_MEMBER not in {member.value for member in FailureClassification}, (
            "this test's input has become a real member, so it no longer "
            "exercises a value the reader does not know"
        )
        payload = _failed(REFUSED_ID, _refusal_error()).model_dump()
        payload["failure_classification"] = _NEVER_A_MEMBER

        projection = WorkflowExecutionDetailProjection(InMemoryProjectionStore())
        await projection.on_workflow_execution_started(_started(REFUSED_ID).model_dump())
        await projection.on_workflow_failed(payload)
        row = await projection.get_by_id(REFUSED_ID)

        assert row is not None
        assert row.failure_classification is FailureClassification.UNCLASSIFIED


class TestATaskFailureIsNotARefusal:
    """#1372: the third class, down the same ten hops as the other two.

    THE DEFECT THIS GUARDS. `correct_refusal` is a claim that the system
    WORKED, and every reported failure made it - including the ones whose agent
    had just said the request could not be done by anybody. Those take opposite
    responses: one is read and closed, the other means the brief is rewritten
    before a single further dollar is spent re-running it. A record that cannot
    separate them sends the operator to re-dispatch, which spends a whole run
    to arrive back at the same sentence.

    WHY THESE TESTS DRIVE BYTES AND NOT AN ENUM. `FailureClassification.TASK`
    existing proves nothing - the issue's own words are that nothing could
    PRODUCE one. So the input here is the text an agent writes, read by the
    production `VerdictReader`, and the assertions are made on what two HTTP
    endpoints answer at the far end. Every hop between is the real one, which
    is what catches the failure mode this file was written for: a value carried
    correctly for nine hops and dropped by a constructor at the tenth.
    """

    @pytest.mark.asyncio
    async def test_the_task_failure_is_named_task(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The end of the chain, on the endpoint an operator opens."""
        task = await _detail(monkeypatch, TASK_ID)

        assert task.failure_classification is FailureClassification.TASK, (
            f"a phase that reported failure_reason=task reaches the API as "
            f"{task.failure_classification.value!r}; the operator reading it "
            f"cannot tell an impossible brief from the gate doing its job"
        )

    @pytest.mark.asyncio
    async def test_it_is_not_the_same_answer_as_a_plain_refusal(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The two runs that differ by ONE key, asked to differ in the record.

        `_REFUSAL_MESSAGES` and `_TASK_MESSAGES` both report `success=false` in
        prose of the same shape. If the reason key is dropped anywhere between
        the agent's text and the response model, these two collapse into one
        answer - and that is exactly the state #1372 was opened about, so it is
        asserted rather than inferred from the member existing.
        """
        task = await _detail(monkeypatch, TASK_ID)
        refused = await _detail(monkeypatch, REFUSED_ID)

        assert task.failure_classification is not refused.failure_classification
        assert refused.failure_classification is FailureClassification.CORRECT_REFUSAL

    @pytest.mark.asyncio
    async def test_the_list_response_carries_it_too(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The other endpoint, off the other projection, on the other model.

        Failure rates are counted over the LIST. A `task` that reaches only the
        detail page answers the one operator who already went looking.
        """
        summaries = await _summaries(monkeypatch)

        assert summaries[TASK_ID].failure_classification is FailureClassification.TASK
        assert summaries[TASK_ID].status == "failed", "the run still failed; this is its KIND"

    @pytest.mark.asyncio
    async def test_all_four_classes_are_distinguishable_in_one_response(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """What the whole field is for, asked of one list response.

        Three live runs and one older than the field, served together, must
        report four different classes. Asserted as a set rather than run by run
        because the property is that the tally SPLITS: any hop that folded two
        of these together would still satisfy every single-run assertion above.
        """
        summaries = await _summaries(monkeypatch, await _projections_with_a_pre_1357_run())

        classes = {
            execution_id: summaries[execution_id].failure_classification
            for execution_id in (TASK_ID, REFUSED_ID, CRASHED_ID, HISTORICAL_ID)
        }

        assert set(classes.values()) == {
            FailureClassification.TASK,
            FailureClassification.CORRECT_REFUSAL,
            FailureClassification.PLATFORM,
            FailureClassification.UNCLASSIFIED,
        }, f"four runs of four kinds do not read as four classes: {classes}"

    @pytest.mark.asyncio
    async def test_it_is_on_the_wire_as_the_word_task(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """What the HTTP client receives, which is the contract the CLI is generated against.

        The enum member could be carried perfectly to the response model and
        still reach a client as something else; `"task"` is the literal the
        regenerated OpenAPI schema and CLI union have to contain, so it is
        asserted after `model_dump` where the wire value is decided.
        """
        detail = (await _detail(monkeypatch, TASK_ID)).model_dump()

        assert detail["failure_classification"] == "task"


class TestARunOlderThanTheFieldItself:
    """#1367 bumped no projection VERSION, so nothing re-projects history.

    Every failure already in the store was recorded by code that did not have
    this field, and will still be served by code that does. What those runs
    answer is therefore not a migration detail - it is the answer the API gives
    for most of the 221 failures the issue counted, indefinitely.

    The contract is the same one `from_stored` exists to keep, asserted where a
    consumer can actually observe it: an explicit `unclassified`, never a null
    in a field the schema declares non-null, never an exception that 500s the
    page, and never a guess - least of all `platform`, which would book the
    quality gate working as the platform breaking and is the exact error #1357
    was opened about.
    """

    @pytest.mark.asyncio
    async def test_the_detail_endpoint_reads_it_as_unclassified(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _serve(monkeypatch, await _projections_with_a_pre_1357_run())
        from syn_api.routes.executions import queries

        historical = await queries.get_execution_endpoint(HISTORICAL_ID)

        assert historical.failure_classification is FailureClassification.UNCLASSIFIED
        assert historical.status == "failed", "the run still failed; only the KIND is unknown"

    @pytest.mark.asyncio
    async def test_the_list_endpoint_reads_it_as_unclassified(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The endpoint the failure NUMBERS are counted over, off the other projection."""
        summaries = await _summaries(monkeypatch, await _projections_with_a_pre_1357_run())

        assert summaries[HISTORICAL_ID].failure_classification is (
            FailureClassification.UNCLASSIFIED
        )
        assert summaries[HISTORICAL_ID].status == "failed"

    @pytest.mark.asyncio
    async def test_it_is_never_guessed_into_platform_or_refusal(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The failure this is really guarding, stated as the thing forbidden.

        A read path that defaulted absence to `platform` would be green on
        every other test in this file and would silently restore #1357's exact
        defect for all of history: `correct_refusal` would be undercounted by
        however many of those 221 runs were the platform working.
        """
        _serve(monkeypatch, await _projections_with_a_pre_1357_run())
        from syn_api.routes.executions import queries

        historical = await queries.get_execution_endpoint(HISTORICAL_ID)

        assert historical.failure_classification not in (
            FailureClassification.PLATFORM,
            FailureClassification.CORRECT_REFUSAL,
        ), (
            "a run recorded before the field existed was given a KIND the "
            "record does not support; the evidence for it was never written"
        )

    @pytest.mark.asyncio
    async def test_the_field_is_present_and_non_null_once_serialized(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """What the HTTP client actually receives, not what the object holds.

        Both response models declare the field non-null, so a `None` reaching
        the wire is a schema violation the generated TypeScript client would
        decode into a lie. Asserted after `model_dump`, because that is the hop
        that decides what is on the wire.
        """
        _serve(monkeypatch, await _projections_with_a_pre_1357_run())
        from syn_api.routes.executions import queries

        detail = (await queries.get_execution_endpoint(HISTORICAL_ID)).model_dump()
        summary = (await _summaries(monkeypatch, await _projections_with_a_pre_1357_run()))[
            HISTORICAL_ID
        ].model_dump()

        for name, body in (("detail", detail), ("summary", summary)):
            assert "failure_classification" in body, f"{name} dropped the field entirely"
            assert body["failure_classification"] == "unclassified", (
                f"{name} put {body['failure_classification']!r} on the wire"
            )

    @pytest.mark.asyncio
    async def test_the_runs_beside_it_still_carry_their_own_kinds(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """What stops the four assertions above from being a default asserted twice.

        `UNCLASSIFIED` is the default on both response models, so a read path
        that never passed the field at all would satisfy every historical
        assertion here. These two runs, served in the SAME responses off the
        SAME projections, can only read this way if the value is genuinely
        carried - which is what makes the historical `unclassified` a resolved
        answer rather than an untouched default.
        """
        summaries = await _summaries(monkeypatch, await _projections_with_a_pre_1357_run())
        _serve(monkeypatch, await _projections_with_a_pre_1357_run())
        from syn_api.routes.executions import queries

        refused = await queries.get_execution_endpoint(REFUSED_ID)

        assert refused.failure_classification is FailureClassification.CORRECT_REFUSAL
        assert summaries[REFUSED_ID].failure_classification is (
            FailureClassification.CORRECT_REFUSAL
        )
        assert summaries[CRASHED_ID].failure_classification is FailureClassification.PLATFORM
