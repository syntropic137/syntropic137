"""Phase-level assertion that a DECLARED delegation actually happened (#894).

Phase success used to be decided SOLELY by ``exit_code == 0``. A phase that
declares ``agent.allow_delegation: true`` is declaring that part of the work
goes to the other harness; when that handoff never lands, the primary agent
still exits 0 and the phase reports success, so the missing half of the work is
invisible to everyone downstream.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
        ExecutablePhase,
    )
    from syn_domain.contexts.orchestration.slices.execute_workflow.handlers.AgentExecutionHandler import (
        AgentExecutionResult,
    )

logger = logging.getLogger(__name__)


def assert_declared_delegation_happened(
    phase_id: str,
    phase: ExecutablePhase,
    result: AgentExecutionResult,
) -> None:
    """Raise if a delegation-enabled phase got no delegate to SUCCEED.

    The assertion is on a successful delegated invocation, not an attempted
    one. In the run that motivated this, the primary agent did launch
    ``codex exec`` and it died on bubblewrap - counting attempts would have
    passed that run. The attempt count rides along in the message so
    "never tried" and "tried and failed" stay distinguishable without anyone
    having to read the transcript.

    Not keyed on the agent's own ``TASK_RESULT`` block: that is self-reported,
    and in the same run the agent openly noted the delegation had failed while
    still reporting ``success: true``.
    """
    if not phase.agent_config.allow_delegation:
        return
    stream = result.stream_result
    if stream.delegation_successes > 0:
        return
    msg = (
        "Declared delegation did not occur "
        f"(phase={phase_id}, provider={phase.agent_config.provider}, "
        f"attempts={stream.delegation_attempts}, successes=0). "
        "The phase declares allow_delegation: true but no delegated CLI "
        "invocation completed successfully, so the phase cannot be reported "
        "as successful."
    )
    logger.error(msg)
    raise RuntimeError(msg)
