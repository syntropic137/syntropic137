"""Declared success assertions for a workflow phase (issue #1085).

Execution status answers "did the agent finish its task". For a phase whose
job is to REPORT a fact rather than change code, the operator needs the answer
to a different question: "does the capability work". The two come apart exactly
when the agent SUCCEEDS at reporting that something is broken, which is the
case `workflows/validation/` exists for. `selfhost-github-ops-v1` reported
`COMMENT: FAILED` and `CLOSE: FAILED`, the agent exited 0, and the execution
finished `completed` - a green row for a deployment missing a GitHub scope.

So a phase declares what its output must contain, and a phase whose output
does not satisfy the declaration fails. The declaration lives in the workflow
definition, beside the assertion prose its author already writes.

WHY THE WORKFLOW DECLARES IT RATHER THAN THE AGENT CLASSIFYING ITSELF. A
`VALIDATION: PASS/FAIL` marker would be less code - the harness already parses
a `TASK_RESULT:` block that nothing reads. It also asks the agent to grade its
own run, and a self-report is not evidence: an agent without a capability will
narrate having used it (docs/handoffs/20260901-handoff_declaration-integrity.md).
Reporting an observable fact is the thing agents do reliably, so the platform
does the judging and the agent only reports.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

#: Patterns are searched with MULTILINE, so `^` and `$` anchor to a LINE.
#: These reports are line-oriented - `ISSUE: 1084` on a line of its own - and
#: an author writing `^CLOSE: ok$` means that line, not an artifact consisting
#: solely of it.
_SEARCH_FLAGS = re.MULTILINE


class PhaseAssertionError(RuntimeError):
    """A phase finished, but its output does not satisfy what it declares.

    Distinct from the exit-code failure it travels beside, because the two mean
    opposite things to an operator: a non-zero exit says the agent broke, this
    says the agent worked and the thing under test did not. The type name
    reaches the failure event as `error_type`, which is where that distinction
    has to survive.
    """

    def __init__(self, phase_id: str, unmet: Sequence[str]) -> None:
        self.phase_id = phase_id
        self.unmet: tuple[str, ...] = tuple(unmet)
        listed = ", ".join(repr(pattern) for pattern in self.unmet)
        verb = "is" if len(self.unmet) == 1 else "are"
        super().__init__(
            f"Phase '{phase_id}' did not report what it asserts: {listed} {verb} "
            f"absent from its collected output. The agent completed; the "
            f"capability it was asked to demonstrate did not."
        )


def require_valid_assertions(value: object) -> object:
    """Return declared assertions unchanged, or raise if one cannot compile.

    Rejecting at AUTHORING time rather than only when the phase completes: a
    bad pattern discovered at completion has already cost a workspace, an agent
    run and the operator's attention, and then fails the execution for a reason
    with nothing to do with the capability under test.

    Non-list and non-string input is passed through so pydantic reports the
    type error in its own words rather than this function inventing a second
    vocabulary for it.
    """
    if value is None:
        return []
    if not isinstance(value, list):
        return value
    for entry in value:
        if not isinstance(entry, str):
            return value
        try:
            re.compile(entry)
        except re.error as err:
            msg = (
                f"asserts entry {entry!r} is not a valid regular expression: {err}. "
                "Each entry is searched against the phase's collected output, so "
                "escape regex metacharacters to match them literally."
            )
            raise ValueError(msg) from err
    return value


def require_asserted_output(
    *,
    phase_id: str,
    assertions: Sequence[str],
    outputs: Iterable[str],
) -> None:
    """Raise unless every declared assertion appears in what the phase produced.

    ``outputs`` is the body of every file the phase left in ``artifacts/output/``.
    An assertion is met when ANY one of them contains it: splitting a report
    across files is a presentation choice, and it should not change whether the
    capability counts as working. A phase that produced nothing satisfies
    nothing, which is the correct answer and not a special case.
    """
    if not assertions:
        return
    bodies = list(outputs)
    unmet = [
        pattern
        for pattern in assertions
        if not any(re.search(pattern, body, _SEARCH_FLAGS) for body in bodies)
    ]
    if unmet:
        raise PhaseAssertionError(phase_id, unmet)
