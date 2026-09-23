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

import asyncio
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

    def __init__(self) -> None:
        super().__init__()
        #: The `context` each reap was asked for, in order. Recorded beside the
        #: bare REAPED entry because WHICH path released the workspace is a
        #: separate question from whether one did: "failure" is the failure
        #: path having cleaned up after itself, and "shutdown" is the sweep at
        #: the end of `run()` having found a workspace nobody released. Both
        #: mean no container leaked; only the first means the failure path is
        #: the reason.
        self.reap_contexts: list[str] = []

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

        async def watched_abandon(context: str) -> None:
            self.append(REAPED)
            self.reap_contexts.append(context)

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
            f"a session report that fails must not be able to precede the event: {list(timeline)}"
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
        assert REAPED in timeline, f"a read-model outage held the workspace open: {list(timeline)}"
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
        assert REAPED in timeline, f"an event-store outage leaked the workspace: {list(timeline)}"
        assert _NOT_DURABLE in caplog.text, (
            "a lost write must say the status is lost; reporting it as a lagging "
            f"read model is how #1318 went unnoticed. Logged: {caplog.text!r}"
        )
        assert _PROJECTION_BEHIND not in caplog.text, (
            "nothing was written, so nothing may be described as recorded"
        )


class TestACancelledShutdownStillReleasesTheWorkspace:
    """`except Exception` is not a guarantee, and this is the gap it leaves.

    `asyncio.CancelledError` inherits BaseException, so every `except
    Exception` in the failure path is blind to it. That makes a shutdown the
    one interruption which can arrive mid-teardown and be caught by nothing -
    and the durable append #1319 added sits in front of the reap, so a
    cancellation landing there used to leave the function with the workspace
    still held. The container then outlives the process that was supposed to
    remove it, which is a cost that keeps accruing after everyone has gone
    home; the failure event it was protecting is lost either way.

    Both tests assert the same two things, because either alone would pass a
    broken implementation:

      - the reap RAN, so nothing leaked;
      - the `CancelledError` still came OUT. A shutdown that is absorbed and
        continues as though it were not cancelled is worse than the leak - it
        is a process ignoring the only instruction it was given. So these
        guards are `finally`, never `except`.
    """

    @pytest.mark.anyio
    async def test_a_cancellation_during_the_durable_append_still_reaps(self) -> None:
        """Cancelled inside `journal.append`, between the write and the reap.

        The narrowest window #1319 opened: the append is deliberately in front
        of the teardown, so it is now the step a shutdown is most likely to
        interrupt.
        """
        timeline = _Timeline()
        processor = _make_processor(FakeAgentExecutionHandler.failed(exit_code=TIMED_OUT))
        timeline.watch(processor)

        repository = processor._journal._repository  # pyright: ignore[reportPrivateUsage]
        permissive_save = repository.save

        async def save_cancelled_by_shutdown(aggregate: object) -> None:
            names = [type(e.event).__name__ for e in aggregate.get_uncommitted_events()]  # pyright: ignore[reportAttributeAccessIssue]
            if "WorkflowFailedEvent" in names:
                raise asyncio.CancelledError
            await permissive_save(aggregate)

        repository.save = save_cancelled_by_shutdown  # pyright: ignore[reportAttributeAccessIssue]

        with pytest.raises(asyncio.CancelledError):
            await processor.run(
                workflow_id="wf-1319-order",
                workflow_name="The failure outlives the container",
                phases=_one_phase_workflow(),
                inputs={},
                execution_id="exec-1319-cancelled-append",
            )

        assert REAPED in timeline, (
            "a shutdown during the append skipped the reap and leaked the workspace "
            f"container - no `except Exception` can see a CancelledError: {list(timeline)}"
        )
        # WHICH path released it, not merely that something did. `run()` sweeps
        # on the way out and would cover this leak too, so asserting only
        # "REAPED" passes whether or not the failure path cleans up after
        # itself - and the sweep is a backstop, not a licence for the path that
        # holds the workspace to hand it over on a cancellation.
        assert "failure" in timeline.reap_contexts, (
            "the failure path let a CancelledError carry the workspace out with it "
            "and left the process-wide sweep to notice the leak; the reap must be "
            f"in a `finally` around the append, not after it: {timeline.reap_contexts}"
        )

    @pytest.mark.anyio
    async def test_a_cancellation_while_the_agent_runs_still_reaps(self) -> None:
        """Cancelled where a shutdown actually lands: inside the agent's run.

        The failure path is not reached at all here - no `WorkflowFailed` is
        ever built - so the reap cannot come from `_fail_execution`. This is
        the same defect one level up, and it covers the minutes-long await
        rather than the millisecond one above.
        """
        timeline = _Timeline()
        processor = _make_processor(FakeAgentExecutionHandler.failed(exit_code=TIMED_OUT))
        timeline.watch(processor)

        async def agent_cancelled_by_shutdown(*_args: object, **_kwargs: object) -> None:
            raise asyncio.CancelledError

        processor._agent_handler.handle = agent_cancelled_by_shutdown  # type: ignore[method-assign]  # pyright: ignore[reportPrivateUsage]

        with pytest.raises(asyncio.CancelledError):
            await processor.run(
                workflow_id="wf-1319-order",
                workflow_name="The failure outlives the container",
                phases=_one_phase_workflow(),
                inputs={},
                execution_id="exec-1319-cancelled-agent",
            )

        assert REAPED in timeline, (
            "a shutdown while the agent was running left the workspace held: the "
            f"terminal paths that reap are both behind `except Exception`: {list(timeline)}"
        )
