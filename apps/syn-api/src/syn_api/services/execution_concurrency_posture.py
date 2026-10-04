"""The startup posture for workflow-execution concurrency (#865).

Moved out of lifecycle.py unchanged (#1545) to keep that file under the
750-line fitness limit; it is still called from startup, once.
"""

from __future__ import annotations

import logging

from syn_shared.env_constants import ENV_SYN_POLLING_MAX_CONCURRENT_DISPATCHES

logger = logging.getLogger(__name__)


def log_execution_concurrency_posture(max_concurrent: int) -> None:
    """Say so when this deployment runs workflows concurrently.

    Called from lifecycle startup beside the capture posture, and for the same
    reason: an operator should learn a risky posture at startup rather than
    from its consequences.

    Emitted HERE, once, rather than while constructing the dispatcher. In the
    dispatcher it fired only if construction got that far, was skipped
    entirely on the test and offline startup paths, and could repeat on every
    subscription-recovery attempt. Posture is a property of the settings, so it
    is reported where the settings are read.

    Concurrent executions are not isolated from each other (#865): they share
    the processor instance holding their per-run state, so one can read
    another's inputs and finish successfully against the wrong target, and one
    execution's cancellation tears down the others' containers.
    """
    if max_concurrent <= 1:
        return

    logger.warning(
        "%s is %d, so workflow executions can run concurrently. They are NOT "
        "yet isolated from each other (#865): concurrent executions can read "
        "each other's inputs and finish against the wrong target, and one "
        "execution's cancellation tears down the others' containers. Set it "
        "to 1 until that is fixed.",
        ENV_SYN_POLLING_MAX_CONCURRENT_DISPATCHES,
        max_concurrent,
    )
