"""#1319: the status a phase died with must survive the workspace being reaped.

THE FAILURE THESE EXIST TO STOP. A phase that exits non-zero raises before
``aggregate.agent_execution_completed`` is ever reached, so
``AgentExecutionCompleted`` - the one event that carries ``exit_code`` - is
written ONLY on the zero-exit path. Every status that actually distinguishes
the outcomes went into the text of a ``RuntimeError`` and no further:

    raise RuntimeError(f"... (exit_code={result.command.exit_code})")

By the time anyone asks, the platform has force-removed the workspace
container, so nothing can re-derive it - and `docker inspect` could not answer
it even before the reap, because the container's PID 1 is ``sleep infinity``
and its status reports the stop signal rather than what the agent did. Two
containers died during the read-model outage in #1318 and neither status was
recoverable.

0, 124 and -11 call for OPPOSITE responses - the run finished, it reached its
time budget and the work should be continued, it was killed and should be
retried - so "unavailable" is the one answer that serves none of them.

These drive the whole ``run()`` loop rather than the assembly helpers, because
the claim is about a RECORDED OUTCOME: what the durable ``WorkflowFailed``
event carries after a real agent double exits non-zero, and what the read model
an operator queries stores when fed that event exactly as production
serializes it.
"""

from __future__ import annotations

import pytest

from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore
from syn_domain.contexts.orchestration.slices.execute_workflow.execution_journal import (
    ExecutionJournal,
)
from syn_domain.contexts.orchestration.slices.get_execution_detail.projection import (
    WorkflowExecutionDetailProjection,
)
from syn_domain.testing.fake_agent_handler import FakeAgentExecutionHandler

from .test_processor_smoke import _make_processor, _one_phase_workflow

pytestmark = pytest.mark.unit

#: The two statuses the issue is about, and neither is reachable by accident.
#: 124 is what the phase timeout wrapper returns when the budget is reached;
#: -11 is a SIGSEGV kill (#1295). A default, a truthiness slip or a status
#: rebuilt from `status == "failed"` produces 0, 1 or None - never either of
#: these - so the exact number appearing downstream could only have been
#: carried there from the agent that exited with it.
TIMED_OUT = 124
SEGFAULTED = -11


async def _failed_event_of_a_phase_that_exited(exit_code: int) -> dict:
    """Run a one-phase workflow whose agent exits `exit_code`, return its event.

    Serialized through ``ExecutionJournal._serialize_event``, which is what
    production hands to the projections - so anything this dict does not carry
    is genuinely unreachable from the read path, not merely unread by a test.
    """
    execution_id = f"exec-1319-{abs(exit_code)}"
    processor = _make_processor(FakeAgentExecutionHandler.failed(exit_code=exit_code))

    # The repository clears uncommitted events on save (as the real SDK one
    # does), so the events are taken as they go past rather than afterwards.
    repository = processor._journal._repository  # pyright: ignore[reportPrivateUsage]
    recorded: list[object] = []
    original_save = repository.save

    async def capturing_save(aggregate: object) -> None:
        recorded.extend(e.event for e in aggregate.get_uncommitted_events())  # pyright: ignore[reportAttributeAccessIssue]
        await original_save(aggregate)

    repository.save = capturing_save  # pyright: ignore[reportAttributeAccessIssue]

    result = await processor.run(
        workflow_id="wf-1319",
        workflow_name="Exit status survives the reap",
        phases=_one_phase_workflow(),
        inputs={},
        execution_id=execution_id,
    )
    assert result.status == "failed", (
        f"a phase whose agent exited {exit_code} must fail the execution; got {result.status!r}"
    )

    failed = [e for e in recorded if type(e).__name__ == "WorkflowFailedEvent"]
    assert len(failed) == 1, f"expected exactly one WorkflowFailedEvent, got {len(failed)}"
    return ExecutionJournal._serialize_event(failed[0])  # pyright: ignore[reportPrivateUsage]


class TestTheDurableEventCarriesTheStatus:
    """Lane 1, which is what a frozen read model (#1318) does not touch."""

    @pytest.mark.anyio
    @pytest.mark.parametrize("exit_code", [TIMED_OUT, SEGFAULTED])
    async def test_a_non_zero_exit_reaches_the_workflow_failed_event(self, exit_code: int) -> None:
        """The agent exits, the run fails, and the number is IN the event.

        Asserted on the serialized payload rather than on the event object,
        because the payload is what is written to the store and replayed: a
        field present on the model and absent from the wire would pass an
        object-level assertion and still leave the status unrecoverable.
        """
        event_data = await _failed_event_of_a_phase_that_exited(exit_code)

        assert event_data["exit_code"] == exit_code
        assert event_data["failed_phase_id"] == "phase-001", (
            "the status is only actionable attached to the phase it belongs to"
        )

    @pytest.mark.anyio
    async def test_a_failure_with_no_process_behind_it_reports_no_status(self) -> None:
        """None, not 0 - and this is the assertion the field exists for.

        An execution stranded by an API restart, or failed before any agent
        ran, has no status to report and must not claim a clean exit. If this
        ever reads 0 the field has become undiagnostic: every consumer would
        have to treat "finished fine" and "nobody was watching" alike, which is
        the state #1319 describes.
        """
        from syn_domain.contexts.orchestration.slices.execute_workflow.phase_outcome import (
            failed_phase_outcome,
        )

        failure = failed_phase_outcome(TimeoutError(), "phase-001", {}, {})

        assert failure.exit_code is None
        assert (
            failure.as_command("exec-1319-none", completed_phases=0, total_phases=1).exit_code
            is None
        )


class TestTheReadModelStoresTheStatus:
    """WorkflowExecutionDetailProjection backs GET /executions/{id}."""

    @pytest.mark.anyio
    async def test_the_failed_phase_row_carries_the_status(self) -> None:
        """The hop from event to stored row, which is where a field gets dropped.

        Fed the real serialized event and read back out of the store, so this
        fails if the projection forwards the execution's other failure fields
        and not this one.
        """
        event_data = await _failed_event_of_a_phase_that_exited(TIMED_OUT)

        detail = WorkflowExecutionDetailProjection(InMemoryProjectionStore())
        await detail.on_workflow_execution_started(
            {"execution_id": event_data["execution_id"], "workflow_id": "wf-1319"}
        )
        await detail.on_phase_started(
            {
                "execution_id": event_data["execution_id"],
                "phase_id": "phase-001",
                "phase_name": "Smoke Phase",
            }
        )

        await detail.on_workflow_failed(event_data)

        row = await detail._store.get(  # pyright: ignore[reportPrivateUsage]
            detail.PROJECTION_NAME, event_data["execution_id"]
        )
        assert row is not None
        phase = next(p for p in row["phases"] if p["phase_id"] == "phase-001")
        assert phase["status"] == "failed"
        assert phase["exit_code"] == TIMED_OUT
