"""#1303: a capacity blip must not destroy an execution, and must not hide one.

THE LOSS, verbatim from the stored record::

    Agent failed: codex reported: Selected model is at capacity.
    Please try a different model. (phase=verify, exit_code=1)

Twice in one window, $18.63, both at `verify` - the third phase of four. The
premise check and the implementation had already run and the branch was already
pushed. The upstream was full for a few seconds and every one of those phases
was discarded.

THE TWO DIRECTIONS THIS CAN BE WRONG, and they are opposite, so a test for one
of them alone is satisfied by a change that is badly wrong in the other:

  - Not retrying. `test_a_busy_upstream_gets_another_attempt` fails against
    `main` on both of its assertions: one attempt, execution failed.
  - Retrying so hard that a real failure is hidden, or a spent budget is
    reported as something other than what actually happened.
    `TestAPermanentFailureStaysPermanent` is the whole of that side. A retry
    wrapper that swallows the final cause is WORSE than no retry: the run still
    fails, and the operator is now reading a story about retrying instead of
    "you are not logged in".

The cases are driven through `processor.run()` rather than the policy, because
every claim here is about a RECORDED OUTCOME - the status, the message an
operator reads, and how many times the agent was actually asked. The policy's
own arithmetic is pinned separately in
`packages/syn-domain/.../test_busy_upstream.py`; neither file is sufficient
alone, since a correct policy that no caller consults changes nothing.
"""

from __future__ import annotations

import pytest

from syn_domain.contexts.orchestration.slices.execute_workflow.busy_upstream import (
    UpstreamRetryPolicy,
)
from syn_domain.testing.fake_agent_handler import FakeAgentExecutionHandler

from .test_processor_smoke import _make_processor, _one_phase_workflow

pytestmark = pytest.mark.unit

#: The issue's signature, exactly as `CodexStreamProcessor` spells it.
AT_CAPACITY = "codex reported: Selected model is at capacity. Please try a different model."

#: The same shape from the other provider. Both harnesses fail this way and
#: the loss is identical, so both are covered - see `busy_upstream`.
OVERLOADED = "API overloaded (HTTP 529)"

#: A codex failure that a second attempt would hit again, word for word. The
#: control for the whole change.
NOT_LOGGED_IN = "codex reported: You are not logged in. Run `codex login` to continue."

SUCCEEDED = 'TASK_RESULT: {"success": true, "comments": "verified"}\nTASK_RESULT_END'

#: Production's bound and schedule with the waiting removed. The ATTEMPT COUNT
#: is production's on purpose: a test that also relaxed the bound would prove
#: nothing about how many attempts a real phase gets.
NO_WAITING = UpstreamRetryPolicy(base_delay_seconds=0.0)


class TestABusyUpstreamIsRetried:
    """The blip costs a wait, not the run."""

    async def test_a_busy_upstream_gets_another_attempt(self) -> None:
        """The issue, end to end: full once, then answered.

        Both assertions fail against `main`, and they fail differently on
        purpose - `call_count` says the retry never happened, `status` says
        what that cost.
        """
        fake = FakeAgentExecutionHandler.scripted(
            FakeAgentExecutionHandler.failed(reason=AT_CAPACITY),
            FakeAgentExecutionHandler.success(says=SUCCEEDED),
        )
        processor = _make_processor(fake, retry_policy=NO_WAITING)

        result = await processor.run(
            workflow_id="wf-1303",
            workflow_name="Busy upstream",
            phases=_one_phase_workflow(),
            inputs={},
            execution_id="exec-1303-recovers",
        )

        assert fake.call_count == 2, (
            "The phase was asked once. A capacity message is the upstream "
            "reporting its own state, not a verdict on this phase."
        )
        assert result.status == "completed", (
            f"Expected 'completed' but got '{result.status}': the second "
            "attempt succeeded and the execution was thrown away anyway."
        )

    async def test_the_other_provider_is_covered_too(self) -> None:
        """Claude reports the same condition in its own words (#1303 scope).

        Fixing only the string in the issue would leave the identical loss
        open on every claude phase, which is most of them.
        """
        fake = FakeAgentExecutionHandler.scripted(
            FakeAgentExecutionHandler.failed(reason=OVERLOADED),
            FakeAgentExecutionHandler.success(says=SUCCEEDED),
        )
        processor = _make_processor(fake, retry_policy=NO_WAITING)

        result = await processor.run(
            workflow_id="wf-1303",
            workflow_name="Overloaded upstream",
            phases=_one_phase_workflow(),
            inputs={},
            execution_id="exec-1303-overloaded",
        )

        assert fake.call_count == 2
        assert result.status == "completed"


class TestAPermanentFailureStaysPermanent:
    """The half that a retry is most likely to break."""

    async def test_an_exhausted_budget_still_fails_with_the_cause_intact(self) -> None:
        """Capacity that never comes back is still a failed execution.

        Two claims, and the second is the one worth having: the run fails, AND
        the message an operator reads is the upstream's own words, unchanged.
        A retry that reported "gave up after 3 attempts" instead would have
        destroyed the only sentence that says what to do about it.
        """
        fake = FakeAgentExecutionHandler.scripted(
            FakeAgentExecutionHandler.failed(reason=AT_CAPACITY)
        )
        processor = _make_processor(fake, retry_policy=NO_WAITING)

        result = await processor.run(
            workflow_id="wf-1303",
            workflow_name="Busy upstream forever",
            phases=_one_phase_workflow(),
            inputs={},
            execution_id="exec-1303-exhausted",
        )

        assert result.status == "failed", (
            "A transient condition that never cleared was reported as a "
            "success. The retry swallowed the failure it ran out of budget on."
        )
        assert fake.call_count == NO_WAITING.max_attempts, (
            f"{fake.call_count} attempts against a bound of "
            f"{NO_WAITING.max_attempts}: the retry is unbounded."
        )
        assert result.error_message is not None
        assert "Selected model is at capacity" in result.error_message, (
            f"The cause was rewritten on the way out: {result.error_message!r}"
        )
        assert "exit_code=1" in result.error_message

    async def test_a_genuine_error_is_not_retried(self) -> None:
        """THE CONTROL. A login that is not valid will not become valid.

        Retrying it spends the phase's budget again to reach the identical
        message, and turns one loss into three. This is what stops the fix for
        #1303 from being a fix that costs more than the bug.
        """
        fake = FakeAgentExecutionHandler.scripted(
            FakeAgentExecutionHandler.failed(reason=NOT_LOGGED_IN)
        )
        processor = _make_processor(fake, retry_policy=NO_WAITING)

        result = await processor.run(
            workflow_id="wf-1303",
            workflow_name="Not logged in",
            phases=_one_phase_workflow(),
            inputs={},
            execution_id="exec-1303-auth",
        )

        assert fake.call_count == 1, (
            f"Asked {fake.call_count} times for a failure that cannot change. "
            "Every attempt after the first is spent reaching the same message."
        )
        assert result.status == "failed"
        assert result.error_message is not None
        assert "You are not logged in" in result.error_message

    async def test_a_cancelled_phase_is_not_retried(self) -> None:
        """An operator's stop outranks the upstream's excuse.

        The combination is the point and it is why the interrupt is checked
        AHEAD of the policy rather than left to the signature list: this phase
        was cancelled while the provider happened to be full, so its reason IS
        on the list. Consulting the policy first would restart, three times
        over, work somebody just stopped.
        """
        fake = FakeAgentExecutionHandler.scripted(
            FakeAgentExecutionHandler(interrupt=True, exit_code=1, reason=AT_CAPACITY)
        )
        processor = _make_processor(fake, retry_policy=NO_WAITING)

        result = await processor.run(
            workflow_id="wf-1303",
            workflow_name="Cancelled mid-phase",
            phases=_one_phase_workflow(),
            inputs={},
            execution_id="exec-1303-cancelled",
        )

        assert fake.call_count == 1
        assert result.status == "cancelled"
