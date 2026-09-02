"""Declared success assertions on a phase's collected artifact (#1085).

An agent can finish a phase cleanly - no crash, no non-zero exit - while
accurately reporting that the capability it was checking is broken. Nothing
upstream of ``ExecutablePhase.success_assertion`` ever reads the artifact
BODY, so ``ExecutionStatus`` lands on ``COMPLETED`` regardless: the dashboard
shows a green row for a validation run whose own artifact says a capability
failed. Extracted rather than inlined in ``WorkflowExecutionProcessor``
because that module carries a 750-line fitness ceiling and stays under it by
pulling each self-contained concern out to its own file (see
``phase_outcome.py`` for the same pattern applied to phase completion/failure
outcomes).
"""

from __future__ import annotations


class PhaseAssertionFailedError(RuntimeError):
    """Raised when a phase's declared ``success_assertion`` is not met.

    Routes through the SAME failure path an agent crash already takes
    (``WorkflowExecutionProcessor.run``'s ``except Exception`` ->
    ``FailExecutionCommand``), so a failed assertion lands on
    ``ExecutionStatus.FAILED`` exactly like a crashed agent, and the
    dashboard badge (which renders ``ExecutionStatus`` directly) reflects it
    with no dashboard change required.
    """


def check_phase_success_assertion(
    phase_id: str,
    success_assertion: str | None,
    content: str | None,
) -> None:
    """Raise ``PhaseAssertionFailedError`` if a declared assertion is absent.

    A no-op when the phase declares no assertion (``success_assertion`` is
    ``None``), so a workflow authored before this field existed keeps
    behaving exactly as it did.

    Args:
        phase_id: The phase whose artifact is being checked, for the error.
        success_assertion: The string that must appear verbatim in
            ``content``, or ``None`` if the phase declares no assertion.
        content: The phase's collected artifact content (the FULL content,
            not a truncated preview - the assertion may name text past the
            preview cutoff).
    """
    if not success_assertion:
        return
    if content is None or success_assertion not in content:
        msg = (
            f"Phase '{phase_id}' failed its declared success assertion: "
            f"expected the collected artifact to contain {success_assertion!r}."
        )
        raise PhaseAssertionFailedError(msg)
