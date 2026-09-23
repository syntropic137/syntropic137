"""Whether an agent run may be recorded as completed, and what failed it (#1367).

THE FAILURE THIS EXISTS TO STOP. The processor asked the phase's own verdict
first and raised on it, and only then looked at how the process had died. So a
run that wrote ``TASK_RESULT success=false`` and was then killed - a timeout
(124), a signal (-11 or 139), an OOM kill (137), an ordinary non-zero exit, or
a codex stream so broken the handler forced it to exit 1 - was recorded as a
CORRECT REFUSAL: the quality gate doing its job. That is precisely backwards.
Those runs are the platform breaking, and they were being counted as evidence
that it works, by the very field #1357 added to tell the two apart.

THE RULE, AND WHY IT IS A CONJUNCTION. A correct refusal is a POSITIVE claim -
"the system ran, and the work was judged not deliverable" - so every part of
it has to be evidenced. It requires ALL of: a readable ``success=false``
report, a clean exit, nothing wrong with the stream, and no cancellation.
Anything else is `PLATFORM`, which is the direction of doubt the enum already
documents: overstating our own failures costs a second look, and understating
them hides the outages this field exists to surface.

The conjunction is not spread across the caller. `PhaseReportedFailureError`
is the ONLY door to `CORRECT_REFUSAL` in the system - `classify_failure` maps
every other exception to `PLATFORM` - so the whole rule is enforced by
constructing that exception in exactly one place, here, behind
`_ran_cleanly`. A platform fault does not need to be classified: it only needs
to keep the refusal from being raised, and the ordinary `RuntimeError` it
raises instead already classifies as `PLATFORM` without knowing anything about
this module.

WHAT THIS DELIBERATELY DOES NOT CHANGE: which runs fail. A broken stream on
its own still does not fail a phase that exited 0 and claimed nothing - that
is #1111, a codex telemetry gap over finished work, and failing it discards
the deliverable. A stream fault only costs a refusal its `correct_refusal`
badge; it never invents a failure. The only question this module answers is
what a failure IS, never whether there is one.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syn_domain.contexts.orchestration.slices.execute_workflow.errors import (
    NonZeroExitError,
    PhaseReportedFailureError,
)
from syn_shared.display import format_exit_code

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration.slices.execute_workflow.handlers.AgentExecutionHandler import (
        AgentExecutionResult,
    )


def phase_failure(result: AgentExecutionResult, *, phase_id: str) -> Exception | None:
    """The exception that ends this phase, or None if it may be completed.

    Returns the exception rather than raising it so that the caller keeps the
    one thing it owns - unwinding through its own teardown - while this module
    keeps the one thing it owns: which evidence about a run outranks which.

    The caller does not learn how the answer was reached, and that is the
    point. It used to: the ordering of two `if`s in the middle of a 200-line
    dispatch WAS this policy, and the ordering was wrong.
    """
    command = result.command
    if command is None:
        return RuntimeError(f"Agent run for phase {phase_id} had no completion command")
    exit_code = command.exit_code
    verdict = result.stream_result.verdict
    if _ran_cleanly(result, exit_code=exit_code):
        # The only construction of `PhaseReportedFailureError` in production,
        # and therefore the only path to `CORRECT_REFUSAL`. An UNREADABLE
        # report reaches it too and is classified `PLATFORM` by the verdict
        # itself - see `AgentVerdict.failure_classification`.
        if verdict.refuses_completion:
            return PhaseReportedFailureError(phase_id=phase_id, verdict=verdict)
        return None

    if exit_code == 0 and not verdict.refuses_completion:
        # Something was wrong with the stream and nothing else was. Completing
        # is what this has always done and what #1111 requires it to keep
        # doing.
        return None

    reason = _platform_reason(result, phase_id=phase_id, exit_code=exit_code)
    return NonZeroExitError(reason, exit_code=exit_code)


def _ran_cleanly(result: AgentExecutionResult, *, exit_code: int) -> bool:
    """Did the platform deliver this run intact, whatever the run then said?

    All three terms are the platform's own account of itself, and none of them
    consults the agent. ``interrupt_requested`` is here even though the
    processor routes a cancel before it ever asks: a cancelled run is not
    evidence of anything about the work, and leaving that term to an early
    return in the caller is how it would go missing the next time the caller
    is edited.
    """
    return (
        exit_code == 0
        and result.stream_result.error_reason is None
        and not result.stream_result.interrupt_requested
    )


def _platform_reason(result: AgentExecutionResult, *, phase_id: str, exit_code: int) -> str:
    """What an operator reads when the platform, not the phase, ended the run.

    The token counts are NOT restated here. They are real fields on the
    failure event now, and the prose version double-counted the context re-sent
    every turn - two numbers for one phase, and nothing to say which to believe
    (#1262).

    A refusal that lost to a platform fault is appended rather than dropped.
    The phase did say it had failed, an operator debugging a 124 wants to read
    that, and the only thing being taken away is the CLASSIFICATION - which
    the last paragraph says out loud, because a reader who sees the refusal
    quoted and `platform` recorded beside it would otherwise be entitled to
    think one of them is a bug.
    """
    reason = result.stream_result.error_reason
    rendered_exit = format_exit_code(exit_code)
    base = (
        f"Agent failed: {reason} (phase={phase_id}, exit_code={rendered_exit})"
        if reason
        else f"Agent execution failed for phase {phase_id} (exit_code={rendered_exit})"
    )
    verdict = result.stream_result.verdict
    if not verdict.refuses_completion:
        return base
    return (
        f"{base}\n\n{verdict.refusal(phase_id=phase_id)}\n\n"
        f"The run did not end cleanly, so it is recorded as a platform failure "
        f"rather than as the phase's own refusal: a report followed by a kill "
        f"is not evidence that the work was correctly judged (#1367)."
    )
