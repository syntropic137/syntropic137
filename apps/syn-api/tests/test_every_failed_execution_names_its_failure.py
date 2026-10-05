"""A failed execution, and the phase it failed in, always say why.

Another orchestrator read two failed runs (exec-38ca290f50a6: exit 124;
exec-b633cc744455: codex "Selected model is at capacity") and concluded they
"failed with no error". The text and the classification were both on the
execution; neither was on the PHASE that died, which is where a reader looking
at a phase table goes first.

So this is a sweep, not a scenario: every way a run is known to fail here is
driven through the production chain - exception -> outcome -> aggregate ->
WorkflowFailed -> detail projection -> `GET /executions/{id}` - and every one
must arrive with a non-empty `error_message` and a classification, at the
execution AND on its failed phase. A new failure shape belongs in
`_FAILURES`; a shape that reaches a reader without its reason fails here.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast

import pytest

from syn_adapters.projection_stores import InMemoryProjectionStore
from syn_domain.contexts.orchestration.cleanup.stale_execution_cleaner import (
    StaleExecutionCleaner,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.commands import (
    AgentExecutionCompletedCommand,
    StartPhaseCommand,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    FailureClassification,
    ReportedFailureReason,
    UpstreamFailureKind,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
    StartExecutionCommand,
    WorkflowExecutionAggregate,
)
from syn_domain.contexts.orchestration.domain.events.WorkflowFailedEvent import (
    WorkflowFailedEvent,
)
from syn_domain.contexts.orchestration.domain.read_models.workflow_execution_summary import (
    WorkflowExecutionSummary,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.agent_run_outcome import (
    phase_failure,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.CodexStreamProcessor import (
    CodexStreamProcessor,
    codex_fault_reason,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.errors import (
    NonZeroExitError,
    PhaseReportedFailureError,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.EventStreamProcessor import (
    ApiErrorType,
    StreamResult,
    api_error_label,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.handlers.AgentExecutionHandler import (
    AgentExecutionResult,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.phase_outcome import (
    failed_phase_outcome,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.phase_verdict import VerdictReader
from syn_domain.contexts.orchestration.slices.execute_workflow.SubagentTracker import (
    SubagentTracker,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.TokenAccumulator import (
    TokenAccumulator,
)
from syn_domain.contexts.orchestration.slices.get_execution_detail.projection import (
    WorkflowExecutionDetailProjection,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable

    from event_sourcing import DomainEvent

    from syn_api.routes.executions.models import ExecutionDetailResponse
    from syn_domain.contexts.orchestration.cleanup.stale_execution_cleaner import (
        ExecutionProjectionProtocol,
        ExecutionRepositoryProtocol,
    )
    from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
        WorkflowExecutionAggregate as _Aggregate,
    )
    from syn_domain.contexts.orchestration.ports.WorkflowExecutionRepositoryPort import (
        WorkflowExecutionRepositoryPort,
    )
    from syn_shared.settings.github import GitHubAppSettings

    FailWith = Callable[[_Aggregate], Awaitable[None]]

pytestmark = pytest.mark.unit

WORKFLOW_ID = "wf-failure-sweep"
PHASE_ID = "implement"
_STARTED_AT = datetime(2026, 10, 5, 9, 0, tzinfo=UTC)
_FAILED_AT = datetime(2026, 10, 5, 9, 20, tzinfo=UTC)


def _reported(*messages: str) -> PhaseReportedFailureError:
    """What a phase dies on when its agent's own report ended it, read for real."""
    reader = VerdictReader()
    for message in messages:
        reader.read(message)
    return PhaseReportedFailureError(phase_id=PHASE_ID, verdict=reader.verdict)


def _upstream(reason: str) -> Exception:
    """What `phase_failure` raises for an attempt whose harness reported `reason`.

    `reason` is produced by the stream processors' own normalisers, and the
    exception by the production function that reads it through the
    `UpstreamFailureReader` port - not a hand-written `RuntimeError`.
    """
    result = AgentExecutionResult(
        stream_result=StreamResult(
            line_count=1, interrupt_requested=False, interrupt_reason=None, error_reason=reason
        ),
        tokens=TokenAccumulator(),
        subagents=SubagentTracker(),
        command=AgentExecutionCompletedCommand(
            execution_id="exec", phase_id=PHASE_ID, session_id="sess", exit_code=1
        ),
    )
    failure = phase_failure(result, phase_id=PHASE_ID)
    assert failure is not None
    return failure


def _github(status_or_drop: int | None) -> Exception:
    """What a real `GitHubAppClient` raises minting a token over a scripted network.

    None drops every connection, so the retrying transport exhausts its three
    attempts; an int answers the mint with that status. Built by the production
    client and transport, not by hand, so the exception's kind is the one a
    provisioning failure actually carries (#1593).
    """
    import httpx

    from syn_adapters.github.client import GitHubAppClient
    from syn_adapters.github.client_retry import RetryPolicy

    def answer(_request: httpx.Request) -> httpx.Response:
        if status_or_drop is None:
            raise httpx.RemoteProtocolError("Server disconnected without sending a response.")
        return httpx.Response(status_or_drop, json={"message": "scripted"})

    settings = cast("GitHubAppSettings", _GitHubSettings())
    client = GitHubAppClient(settings, transport=httpx.MockTransport(answer))
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(GitHubAppClient, "_generate_jwt", lambda _self: "jwt")
        patch.setattr(RetryPolicy, "delay_after", lambda _self, _attempt: 0.0)
        try:
            asyncio.run(client.get_installation_token("7"))
        except Exception as raised:
            return raised
    raise AssertionError("the scripted mint did not fail")


@dataclass(frozen=True)
class _GitHubSettings:
    is_configured: bool = True
    bot_name: str = "syn-bot"
    bot_email: str = "bot@example.com"


class _SilentRecorder:
    """A codex observability recorder that records nothing: only the verdict is read."""

    def note_agent_activity(self) -> None:
        return

    def note_observed_model(self, model: str | None) -> None:
        return

    async def record_tool_started(self, **_kwargs: object) -> None:
        return

    async def record_tool_completed(self, **_kwargs: object) -> None:
        return

    async def record_token_usage(self, *_args: object, **_kwargs: object) -> None:
        return

    async def record_session_summary(self, **_kwargs: object) -> None:
        return


class _Workspace:
    last_stream_exit_code = 1

    async def interrupt(self) -> bool:
        return True


def _codex_parsed(*lines: str) -> str:
    """The `error_reason` the real codex stream processor gives these raw stdout lines."""

    async def stream() -> AsyncIterator[str]:
        for line in lines:
            yield line

    processor = CodexStreamProcessor(
        tokens=TokenAccumulator(),
        collector=_SilentRecorder(),
        controller=None,
        execution_id="exec",
        phase_id=PHASE_ID,
        session_id="sess",
        agent_model="gpt-5.6",
        rollout=None,
    )
    result = asyncio.run(processor.process_stream(stream(), _Workspace()))
    assert result.error_reason is not None
    return result.error_reason


#: The real codex sentence (#1303) and a claude 401, as the parsers spell them.
CODEX_AT_CAPACITY = codex_fault_reason(
    "Selected model is at capacity. Please try a different model."
)
CLAUDE_UNAUTHORISED = api_error_label(ApiErrorType.AUTHENTICATION, "401")
#: The codex login fault from the production run behind #1303, as raw stdout:
#: the parser appends the CLI's own log line to the 401 label.
CODEX_UNAUTHORISED = _codex_parsed(
    "ERROR codex_login::auth::manager: Failed to refresh token: 401 Unauthorized "
    '- {"error": "invalid_grant", "code": "refresh_token_reused"}'
)

#: Every exception a phase is known to die on in the processor, by execution id.
_PHASE_FAILURES: dict[str, BaseException] = {
    # exec-38ca290f50a6's shape: the phase hit its wall-clock budget.
    "exec-timeout": NonZeroExitError("agent exited with code 124", exit_code=124),
    # exec-b633cc744455's shape: the harness reported the model unavailable.
    "exec-capacity": _upstream(CODEX_AT_CAPACITY),
    "exec-auth": _upstream(CLAUDE_UNAUTHORISED),
    "exec-codex-auth": _upstream(CODEX_UNAUTHORISED),
    # exec-2bb840f5c9b6's shape: GitHub dropped the connection while the
    # workspace's token was minted, on every attempt the transport allowed.
    "exec-github-unavailable": _github(None),
    "exec-github-auth": _github(401),
    "exec-crash": RuntimeError("workspace container exited 137 before the agent reported"),
    "exec-refusal": _reported(
        'TASK_RESULT: {"success": false, "comments": "premise false"}\nTASK_RESULT_END'
    ),
    "exec-task": _reported(
        'TASK_RESULT: {"success": false, "failure_reason": "task", '
        '"comments": "the brief names a module that does not exist"}\nTASK_RESULT_END'
    ),
    "exec-unreadable": _reported("TASK_RESULT: {success: probably not"),
    # A readable report that says "I cannot tell": the one current-code shape
    # that is DELIBERATELY unclassified (`classification_for_reported`).
    "exec-unknown": _reported(
        'TASK_RESULT: {"success": false, "failure_reason": "unknown", '
        '"comments": "the run died and I cannot tell why"}\nTASK_RESULT_END'
    ),
}


class _Repository:
    """The one aggregate under test, behind both repository ports that fail runs."""

    def __init__(self, aggregate: WorkflowExecutionAggregate) -> None:
        self.aggregate = aggregate

    async def get(self, _execution_id: str) -> WorkflowExecutionAggregate:
        return self.aggregate

    async def get_by_id(self, _execution_id: str) -> WorkflowExecutionAggregate:
        return self.aggregate

    async def save(self, _aggregate: WorkflowExecutionAggregate) -> None:
        return None


def _processor(error: BaseException, *, phase_started: bool) -> FailWith:
    """`WorkflowExecutionProcessor._fail_execution`'s path: exception -> outcome -> command."""

    async def fail(aggregate: WorkflowExecutionAggregate) -> None:
        outcome = failed_phase_outcome(
            error,
            phase_id=PHASE_ID if phase_started else None,
            started_at_by_phase={PHASE_ID: _STARTED_AT} if phase_started else {},
            session_id_by_phase={},
            now=_FAILED_AT,
        )
        aggregate.fail_execution(
            outcome.as_command(aggregate.id, completed_phases=0, total_phases=1)
        )

    return fail


async def _stale_cleaner(aggregate: WorkflowExecutionAggregate) -> None:
    """`StaleExecutionCleaner`: a run past its wall-clock threshold."""
    cleaner = StaleExecutionCleaner(
        projection=cast("ExecutionProjectionProtocol", None),
        execution_repository=cast("ExecutionRepositoryProtocol", _Repository(aggregate)),
    )
    await cleaner._mark_as_failed(aggregate.id, "stale", "running for 25h with no progress")


async def _restart_reconciliation(aggregate: WorkflowExecutionAggregate) -> None:
    """Startup reconciliation: a run the restart orphaned."""
    from syn_api.services import reconciliation

    async def _nothing_salvaged(*_args: object, **_kwargs: object) -> None:
        return None

    summary = WorkflowExecutionSummary(
        workflow_execution_id=aggregate.id,
        workflow_id=WORKFLOW_ID,
        workflow_name="implement-verify-report",
        status="running",
        started_at=_STARTED_AT,
        completed_at=None,
        completed_phases=0,
        total_phases=1,
        total_tokens=0,
    )
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(reconciliation, "_salvage_before_failing", _nothing_salvaged)
        outcome = await reconciliation._reconcile_one(
            summary,
            repository=cast("WorkflowExecutionRepositoryPort", _Repository(aggregate)),
        )
    assert aggregate.status.value == "failed", outcome


#: Every production emitter of WorkflowFailed (`git grep "fail_execution("`),
#: with and without a phase started: (fails the run, a phase was started).
_FAILURES: dict[str, tuple[FailWith, bool]] = {
    **{eid: (_processor(err, phase_started=True), True) for eid, err in _PHASE_FAILURES.items()},
    # Dies before any phase starts: workspace provisioning, setup, gates.
    "exec-before-any-phase": (
        _processor(RuntimeError("workspace provisioning failed"), phase_started=False),
        False,
    ),
    "exec-stale-mid-phase": (_stale_cleaner, True),
    "exec-stale-before-any-phase": (_stale_cleaner, False),
    "exec-orphaned-mid-phase": (_restart_reconciliation, True),
    "exec-orphaned-before-any-phase": (_restart_reconciliation, False),
}

#: Executions whose failed phase exists, so it must say why it failed.
_WITH_A_FAILED_PHASE = sorted(eid for eid, (_, started) in _FAILURES.items() if started)


async def _failure_events(execution_id: str) -> list[DomainEvent]:
    """Every event the REAL aggregate emits for this run, through its real failure path."""
    fail, phase_started = _FAILURES[execution_id]
    aggregate = WorkflowExecutionAggregate()
    aggregate.start_execution(
        StartExecutionCommand(
            execution_id=execution_id,
            workflow_id=WORKFLOW_ID,
            workflow_name="implement-verify-report",
            total_phases=1,
            inputs={},
        )
    )
    if phase_started:
        aggregate.start_phase(
            StartPhaseCommand(
                execution_id=execution_id,
                workflow_id=WORKFLOW_ID,
                phase_id=PHASE_ID,
                phase_name=PHASE_ID,
                phase_order=0,
            )
        )
    await fail(aggregate)
    events = [envelope.event for envelope in aggregate.get_uncommitted_events()]
    assert events[-1].event_type == "WorkflowFailed", events[-1].event_type
    return events


@dataclass
class _StubProjectionManager:
    store: InMemoryProjectionStore
    workflow_execution_detail: WorkflowExecutionDetailProjection


async def _projections() -> _StubProjectionManager:
    store = InMemoryProjectionStore()
    detail = WorkflowExecutionDetailProjection(store)
    handlers = {
        "WorkflowExecutionStarted": detail.on_workflow_execution_started,
        "PhaseStarted": detail.on_phase_started,
        "WorkflowFailed": detail.on_workflow_failed,
    }
    for execution_id in _FAILURES:
        for event in await _failure_events(execution_id):
            await handlers[event.event_type](event.model_dump())
    return _StubProjectionManager(store=store, workflow_execution_detail=detail)


async def _detail(
    monkeypatch: pytest.MonkeyPatch, manager: _StubProjectionManager, execution_id: str
) -> ExecutionDetailResponse:
    """Serve `GET /executions/{id}` off projections built from real events."""
    from syn_api import _wiring
    from syn_api.routes.executions import queries

    async def _noop_connect() -> None:
        return None

    monkeypatch.setattr(queries, "ensure_connected", _noop_connect)
    monkeypatch.setattr(queries, "get_projection_mgr", lambda: manager)
    monkeypatch.setattr(_wiring, "get_projection_mgr", lambda: manager)
    return await queries.get_execution_endpoint(execution_id)


@pytest.mark.asyncio
@pytest.mark.parametrize("execution_id", sorted(_FAILURES))
async def test_a_failed_execution_carries_its_error_and_classification(
    monkeypatch: pytest.MonkeyPatch, execution_id: str
) -> None:
    detail = await _detail(monkeypatch, await _projections(), execution_id)

    assert detail.status == "failed"
    assert detail.error_message, f"{execution_id} failed with an empty error_message"
    assert isinstance(detail.failure_classification, FailureClassification), (
        f"{execution_id} failed with no classification"
    )
    # Unclassified is a classification only when the phase itself said it
    # cannot tell; from anything else today's code must have decided.
    if detail.failure_classification is FailureClassification.UNCLASSIFIED:
        assert detail.reported_failure_reason is ReportedFailureReason.UNKNOWN, (
            f"{execution_id} was produced by today's code and still reads unclassified"
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("execution_id", _WITH_A_FAILED_PHASE)
async def test_the_failed_phase_carries_the_same_error_and_classification(
    monkeypatch: pytest.MonkeyPatch, execution_id: str
) -> None:
    """The phase a reader opens first says what the execution says.

    Driven to the HTTP model, not stopped at the projection row: the response
    constructor re-lists every phase field by hand and is the hop that has
    dropped one before (#891, #1176, #1319).
    """
    detail = await _detail(monkeypatch, await _projections(), execution_id)

    (phase,) = detail.phases
    assert phase.status == "failed"
    assert phase.error_message, f"{execution_id}'s failed phase has no error_message"
    assert phase.error_message == detail.error_message, (
        f"{execution_id}: execution says {detail.error_message!r}, "
        f"its failed phase says {phase.error_message!r}"
    )
    assert phase.failure_classification is detail.failure_classification, (
        f"{execution_id}: execution says {detail.failure_classification!r}, "
        f"its failed phase says {phase.failure_classification!r}"
    )
    assert phase.reported_failure_reason == detail.reported_failure_reason


@pytest.mark.asyncio
async def test_capacity_and_auth_say_what_they_ask_of_an_operator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both are `platform`; the record still says which wants a wait and which a fix."""
    manager = await _projections()
    capacity = await _detail(monkeypatch, manager, "exec-capacity")
    auths = [
        await _detail(monkeypatch, manager, "exec-auth"),
        await _detail(monkeypatch, manager, "exec-codex-auth"),
    ]

    for detail in (capacity, *auths):
        assert detail.failure_classification is FailureClassification.PLATFORM
    assert capacity.error_message is not None
    assert "Upstream failure: capacity - transient; the phase is resumable." in (
        capacity.error_message
    )
    for auth in auths:
        assert auth.error_message is not None
        assert "Upstream failure: auth - an operator must fix the credentials." in (
            auth.error_message
        )
        assert "resumable" not in auth.error_message
        (phase,) = auth.phases
        assert phase.error_message == auth.error_message


@pytest.mark.asyncio
async def test_github_unavailable_is_recorded_resumable_and_github_auth_as_an_operators(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Three dropped connections and a 401 are both `platform`, and opposite asks (#1593).

    The kind is asserted on the stored WorkflowFailed event, typed, and the
    sentence an operator reads on the execution and its failed phase.
    """
    unavailable = (await _failure_events("exec-github-unavailable"))[-1]
    auth = (await _failure_events("exec-github-auth"))[-1]
    assert isinstance(unavailable, WorkflowFailedEvent)
    assert isinstance(auth, WorkflowFailedEvent)
    assert unavailable.upstream_failure_kind is UpstreamFailureKind.UNAVAILABLE
    assert auth.upstream_failure_kind is UpstreamFailureKind.AUTH
    assert unavailable.failure_classification is FailureClassification.PLATFORM
    assert auth.failure_classification is FailureClassification.PLATFORM

    manager = await _projections()
    resumable = await _detail(monkeypatch, manager, "exec-github-unavailable")
    operator = await _detail(monkeypatch, manager, "exec-github-auth")
    assert resumable.error_message is not None
    assert "Upstream failure: unavailable - transient; the phase is resumable." in (
        resumable.error_message
    )
    assert operator.error_message is not None
    assert "Upstream failure: auth - an operator must fix the credentials." in (
        operator.error_message
    )
    assert "resumable" not in operator.error_message
    for detail in (resumable, operator):
        (phase,) = detail.phases
        assert phase.error_message == detail.error_message
