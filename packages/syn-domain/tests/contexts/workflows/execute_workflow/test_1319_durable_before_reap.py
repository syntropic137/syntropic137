"""#1319: the failure must be on the event stream before the container is reaped.

WHAT THE ORDER COSTS. A failing phase's exit status exists in exactly one
frame - `_fail_execution`'s - and the teardown it performs destroys the
container that could otherwise be asked again. `report_failed` then
`abandon_all` then append meant every one of these left NO WorkflowFailedEvent
at all:

  - the session repository is down and `report_failed` raises;
  - the process is shut down mid-teardown and the append never runs;
  - teardown itself throws while probing or closing a workspace.

Restart reconciliation can then only record the status as unknown, which is
precisely the outcome #1319 exists to prevent - and #1318 is what it looks like
in production: two containers died during a read-model outage and neither
status was recoverable.

Ordering against destructive cleanup is invisible in a diff and cannot be
asserted anywhere but here, at the layer that owns both halves. These drive the
whole `run()` loop and watch the two ends: what reached the repository, and
when the reap happened relative to it.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import pytest

from syn_domain.testing.fake_agent_handler import FakeAgentExecutionHandler

from .test_processor_smoke import _make_processor, _one_phase_workflow

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration.slices.execute_workflow.WorkflowExecutionProcessor import (
        WorkflowExecutionProcessor,
    )

pytestmark = pytest.mark.unit

#: A status that could only have been carried here from the agent that exited
#: with it: the phase timeout wrapper's (#1295).
TIMED_OUT = 124

#: The two accounts `_fail_execution` can give of a failed append, matched on
#: the phrase that distinguishes them rather than the whole line.
_NOT_DURABLE = "was not durably recorded"
_PROJECTION_BEHIND = "did not apply it"

RECORDED = "recorded:WorkflowFailedEvent"
REPORTED = "sessions-reported"
REAPED = "reaped"


class _Timeline(list[str]):
    """What happened during one run, in the order it happened."""

    def watch(self, processor: WorkflowExecutionProcessor) -> None:
        """Instrument the two ends that must not swap: the store, and the reap."""
        journal = processor._journal  # pyright: ignore[reportPrivateUsage]
        repository = journal._repository  # pyright: ignore[reportPrivateUsage]
        runtime = processor._runtime  # pyright: ignore[reportPrivateUsage]
        original_save = repository.save

        async def watched_save(aggregate: object) -> None:
            for envelope in aggregate.get_uncommitted_events():  # pyright: ignore[reportAttributeAccessIssue]
                self.append(f"recorded:{type(envelope.event).__name__}")
            await original_save(aggregate)

        async def watched_report(_reason: str) -> None:
            self.append(REPORTED)

        async def watched_abandon(_context: str) -> None:
            self.append(REAPED)

        repository.save = watched_save  # pyright: ignore[reportAttributeAccessIssue]
        runtime.report_failed = watched_report  # type: ignore[method-assign]
        runtime.abandon_all = watched_abandon  # type: ignore[method-assign]


async def _run_a_failing_phase(timeline: _Timeline) -> str:
    """Run a one-phase workflow whose agent exits non-zero. Returns its status."""
    processor = _make_processor(FakeAgentExecutionHandler.failed(exit_code=TIMED_OUT))
    timeline.watch(processor)
    result = await processor.run(
        workflow_id="wf-1319-order",
        workflow_name="The failure outlives the container",
        phases=_one_phase_workflow(),
        inputs={},
        execution_id="exec-1319-order",
    )
    return result.status


class TestTheEventIsOnTheStreamFirst:
    @pytest.mark.anyio
    async def test_the_failure_is_recorded_before_anything_is_torn_down(self) -> None:
        """The whole claim of #1319's title, asserted as an order.

        Not "the event exists" - the old code produced it too, when nothing
        went wrong. The claim is that it exists BEFORE the only step that can
        destroy the evidence, so that a teardown which dies takes nothing
        undurable with it.
        """
        timeline = _Timeline()
        assert await _run_a_failing_phase(timeline) == "failed"

        assert RECORDED in timeline, f"no failure event was ever recorded: {list(timeline)}"
        assert REAPED in timeline, f"the workspaces were never released: {list(timeline)}"
        assert timeline.index(RECORDED) < timeline.index(REAPED), (
            f"the container was reaped before the failure was durable: {list(timeline)}"
        )
        assert timeline.index(RECORDED) < timeline.index(REPORTED), (
            "a session report that fails must not be able to precede the event: "
            f"{list(timeline)}"
        )

    @pytest.mark.anyio
    async def test_a_session_report_that_raises_loses_neither_the_event_nor_the_cleanup(
        self,
    ) -> None:
        """The #1318 shape: the thing that reports sessions is down.

        Both halves matter. The event must already be written, and the reap
        must still happen - a container nobody removes is a leaked one, and an
        outage in a reporting path must never be what leaks it.
        """
        timeline = _Timeline()
        processor = _make_processor(FakeAgentExecutionHandler.failed(exit_code=TIMED_OUT))
        timeline.watch(processor)

        async def report_that_is_down(_reason: str) -> None:
            timeline.append(REPORTED)
            raise ConnectionError("session repository is unreachable")

        processor._runtime.report_failed = report_that_is_down  # type: ignore[method-assign]  # pyright: ignore[reportPrivateUsage]

        result = await processor.run(
            workflow_id="wf-1319-order",
            workflow_name="The failure outlives the container",
            phases=_one_phase_workflow(),
            inputs={},
            execution_id="exec-1319-report-down",
        )

        assert result.status == "failed", "the run must still report its own failure"
        assert RECORDED in timeline, (
            f"the failure was lost because reporting the sessions failed: {list(timeline)}"
        )
        assert REAPED in timeline, (
            f"a failed session report skipped the reap and leaked the workspace: {list(timeline)}"
        )


class TestAReadModelOutageCannotBlockCleanup:
    """'The write was lost' and 'the read model is behind' are opposite facts.

    They arrive at `_fail_execution` as one `await` - `journal.append` is the
    store and then this run's local to-do list - and used to be logged as one
    line: "Failed to save failure event". The first means the status is gone
    and somebody has to go looking; the second means it is safe on the stream
    and only a read model is behind, which needs nobody at 2am. Neither may
    stop the reap, and they may not be reported as the same thing, so the log
    line is asserted: it is the whole observable difference and the only thing
    an operator ever sees.
    """

    @pytest.mark.anyio
    async def test_a_projection_that_raises_still_lets_the_workspace_go(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The event committed; only the local projection blew up."""
        caplog.set_level(logging.ERROR)
        timeline = _Timeline()
        processor = _make_processor(FakeAgentExecutionHandler.failed(exit_code=TIMED_OUT))
        timeline.watch(processor)

        async def projection_that_is_down(_event_data: dict) -> None:
            raise ConnectionError("projection store is unreachable")

        processor._todo_projection.on_workflow_failed = projection_that_is_down  # type: ignore[method-assign]  # pyright: ignore[reportPrivateUsage]

        result = await processor.run(
            workflow_id="wf-1319-order",
            workflow_name="The failure outlives the container",
            phases=_one_phase_workflow(),
            inputs={},
            execution_id="exec-1319-projection-down",
        )

        assert result.status == "failed"
        assert RECORDED in timeline, "the event reached the store before the projection ran"
        assert REAPED in timeline, (
            f"a read-model outage held the workspace open: {list(timeline)}"
        )
        assert _NOT_DURABLE not in caplog.text, (
            "a projection outage must not be reported as a lost write - the status "
            "is on the stream, and sending someone to look for it is the wrong call"
        )
        assert _PROJECTION_BEHIND in caplog.text, (
            f"the projection failure went unreported: {caplog.text!r}"
        )

    @pytest.mark.anyio
    async def test_a_store_that_rejects_the_write_still_lets_the_workspace_go(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The other side: nothing was written, and the reap must happen anyway.

        The status is unrecoverable at this point - that is the cost of the
        outage, not something the processor can fix - but leaking the container
        on top of it helps nobody.
        """
        caplog.set_level(logging.ERROR)
        timeline = _Timeline()
        processor = _make_processor(FakeAgentExecutionHandler.failed(exit_code=TIMED_OUT))
        timeline.watch(processor)

        repository = processor._journal._repository  # pyright: ignore[reportPrivateUsage]
        permissive_save = repository.save

        async def save_that_rejects_the_failure(aggregate: object) -> None:
            names = [type(e.event).__name__ for e in aggregate.get_uncommitted_events()]  # pyright: ignore[reportAttributeAccessIssue]
            if "WorkflowFailedEvent" in names:
                raise ConnectionError("event store is unreachable")
            await permissive_save(aggregate)

        repository.save = save_that_rejects_the_failure  # pyright: ignore[reportAttributeAccessIssue]

        result = await processor.run(
            workflow_id="wf-1319-order",
            workflow_name="The failure outlives the container",
            phases=_one_phase_workflow(),
            inputs={},
            execution_id="exec-1319-store-down",
        )

        assert result.status == "failed", (
            "the caller must still be told the run failed, even unrecorded"
        )
        assert RECORDED not in timeline, (
            "the store rejected the write, so nothing may claim it was recorded"
        )
        assert REAPED in timeline, (
            f"an event-store outage leaked the workspace: {list(timeline)}"
        )
        assert _NOT_DURABLE in caplog.text, (
            "a lost write must say the status is lost; reporting it as a lagging "
            f"read model is how #1318 went unnoticed. Logged: {caplog.text!r}"
        )
        assert _PROJECTION_BEHIND not in caplog.text, (
            "nothing was written, so nothing may be described as recorded"
        )
