"""What an agent said about its own outcome, and what "I could not" obliges.

EVERY PHASE PROMPT ENDS WITH THE SAME CONTRACT (`workspace_prompt.py`): the
last thing an agent writes is a ``TASK_RESULT`` block declaring whether it did
the job, and the prompt tells it, in so many words, that this "is how the
orchestrator knows whether to retry, escalate, or mark the task as done".

It was not. The block was parsed off the claude stream into a `dict[str, Any]`,
logged at INFO, carried as far as `StreamResult` - and read by nothing. The
codex path never parsed it at all. So a phase that declared
``{"success": false}`` completed, its artifact was collected, the next phase
ran on it, and the execution reported ``completed``: indistinguishable, on
every surface the platform has, from a phase that did the work (#1127).

WHY THAT IS WORSE THAN A MISSING FEATURE. The phase it was found on is
`sdlc-pr-review-v1`'s `verify` - the cross-model half of the merge gate. It
stops when the head it was told to review has moved, because reviewing a
different tree would certify the wrong code. Stopping is right. Reporting
success while stopping is a gate that lies, and it lies in the direction that
lets defects through: the run is green, the verdict is composed from one phase
instead of two, and nothing on the execution says so. The same shape as a
marker gate that ignores pytest's exit status.

THE INVARIANT THIS MODULE EXISTS TO HOLD: "I could not do this" must be a
DIFFERENT OUTCOME from "I did this and it passed", and nothing downstream may
read the first as the second.

WHERE THE REFUSAL FIRES, and why not sooner. `refuse_to_complete_declared_failure`
is called from the completion path, AFTER the phase's artifacts have been
collected and recorded. Failing at the agent-exit hop instead would have been
one line shorter and would have thrown away the very thing worth keeping: the
write-up saying WHY the phase could not do its job. By refusing at completion,
the artifact is already durable in the event store, the execution fails with
the agent's own words as its reason, and every phase after this one is skipped
- which is the whole point, because they would otherwise build on a phase that
declared it produced nothing to build on.

WHAT THIS DELIBERATELY DOES NOT DO. It never invents a failure. A phase that
writes no ``TASK_RESULT`` block, or writes one whose ``success`` is not a JSON
boolean, has declared nothing, and this module says nothing about it - other
gates (the #1167 output contract, the #1184 unsaved-work guard, the exit code)
answer those. Only an EXPLICIT ``success: false`` is a declared failure. Fail-
closed would be the wrong default here: it would turn every agent that worded
its last line loosely into a failed execution, which is a large blast radius
bought for a signal that was never the point.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Mapping

    from syn_domain.contexts.orchestration._shared.TodoValueObjects import TodoItem

logger = logging.getLogger(__name__)

#: The literal the workspace prompt tells every agent to emit, on every
#: harness. Defined once here because the parser and the prompt must agree and
#: nothing mechanically forces them to.
TASK_RESULT_MARKER: Final[str] = "TASK_RESULT:"


@dataclass(frozen=True)
class AgentSelfReport:
    """The agent's own verdict on its phase, as the agent stated it.

    A value, not a dict: the two fields are the whole of the contract, and the
    `dict[str, Any]` this replaces is exactly what let the verdict be carried
    everywhere and consulted nowhere - nothing about a dict says it has a
    consumer, and nothing about `.get("success")` says what an absent key means.
    """

    succeeded: bool
    comments: str

    @classmethod
    def parse(cls, said: str | None) -> AgentSelfReport | None:
        """Read the ``TASK_RESULT`` block off the last thing an agent said.

        Returns None for "the agent declared nothing", which covers no marker,
        unparseable JSON, and a ``success`` that is not a boolean. See this
        module's docstring for why that is silence rather than failure.

        The LAST marker in the text wins. Agents quote the template while
        explaining themselves, and the contract is that the block is the final
        thing in the response, so scanning from the end reads the declaration
        rather than the explanation of one.
        """
        if not said or TASK_RESULT_MARKER not in said:
            return None
        raw = said[said.rfind(TASK_RESULT_MARKER) + len(TASK_RESULT_MARKER) :].strip()
        brace_end = raw.find("}")
        if brace_end >= 0:
            raw = raw[: brace_end + 1]
        try:
            block = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            logger.debug("Could not parse TASK_RESULT block")
            return None
        if not isinstance(block, dict):
            return None
        succeeded = block.get("success")
        if not isinstance(succeeded, bool):
            return None
        comments = block.get("comments")
        return cls(succeeded=succeeded, comments=str(comments) if comments is not None else "")


class PhaseDeclaredItsOwnFailureError(Exception):
    """The phase's agent said it did not do the job (#1127).

    Carries the agent's own words as the failure reason, because they are the
    only account of WHY that exists at this point and they are what an operator
    reading the execution needs. "Agent execution failed for phase verify" says
    nothing; "the head SHA I was told to review no longer exists on origin"
    says what to do next.
    """

    def __init__(self, *, phase_id: str, comments: str) -> None:
        super().__init__(
            f"Phase '{phase_id}' declared its own failure: it ended with "
            f"TASK_RESULT success=false, so it did not do what it was asked "
            f"and is not a completed phase. The agent's reason: "
            f"{comments.strip() or '(the agent gave none)'}"
        )
        self.phase_id = phase_id
        self.comments = comments


def refuse_to_complete_declared_failure(
    reports: Mapping[str, AgentSelfReport],
    todo: TodoItem,
) -> None:
    """Refuse to complete a phase whose agent declared it did not do the job.

    MUST be called on the completion path before the aggregate is told the
    phase succeeded, and AFTER `refuse_to_complete_unsaved_phase` - that guard
    saves work before refusing, and a refusal ordered ahead of it would strand
    the very commits it exists to rescue (#1184).

    The caller hands over the map and the to-do item and needs to know nothing
    else. A phase that declared nothing, or declared success, returns silently:
    absence of a declaration is not a declaration of absence, and every other
    contract a phase must meet is enforced by its own gate.

    Raises:
        PhaseDeclaredItsOwnFailureError: the agent's last word was
            ``success: false``.
    """
    phase_id = todo.phase_id
    report = reports.get(phase_id) if phase_id is not None else None
    if phase_id is None or report is None or report.succeeded:
        return
    logger.error(
        "Phase %s declared TASK_RESULT success=false; refusing to complete it: %s",
        phase_id,
        report.comments,
    )
    raise PhaseDeclaredItsOwnFailureError(phase_id=phase_id, comments=report.comments)
