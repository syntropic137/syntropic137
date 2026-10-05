"""A live phase workspace's delegations, read from its child journal (#894).

Satisfies `DelegationEvidencePort`. The journal format, and how a harness's
delegate gets into it, belong to agentic-workspace (``syn-delegate`` writes it,
`WorkspaceChildJournalReader` reads it). This adapter only maps the reader's
normalised `ChildIntent` onto the domain's provider-neutral terms.

The journal's location is read from the workspace's own environment rather
than re-derived here: the partition is whatever the session store inside the
container was told, and asking it is the one answer that cannot disagree.
"""

from __future__ import annotations

import shlex
from typing import TYPE_CHECKING

from agentic_isolation.child_journal import JournalReadError, WorkspaceChildJournalReader

# The one ManagedWorkspace -> ExecFn adapter; its `env` parameter is the
# external ExecFn contract and is already accounted for under #1268.
from syn_adapters.workspace_backends.service.codex_rollout import _exec_fn_for
from syn_domain.contexts.orchestration.ports import (
    DelegationAttempt,
    DelegationEvidenceUnavailableError,
    DelegationOutcome,
)
from syn_shared.env_constants import (
    ENV_AGENTIC_SESSION_STORE_PARTITION,
    ENV_AGENTIC_SESSION_STORE_SPOOL,
)

if TYPE_CHECKING:
    from agentic_isolation.child_journal import ChildIntent

    from syn_adapters.workspace_backends.service.managed_workspace import ManagedWorkspace

_OUTCOMES: dict[str, DelegationOutcome] = {
    "completed": DelegationOutcome.SUCCEEDED,
    "failed": DelegationOutcome.FAILED,
    "launch_failed": DelegationOutcome.FAILED,
    "cancelled": DelegationOutcome.CANCELLED,
}


def delegation_attempt(intent: ChildIntent) -> DelegationAttempt | None:
    """The domain's view of one journal intent, None for a native subagent.

    Only a cross-harness child (``target_harness`` set) is a delegation in the
    ``allow_delegation`` sense; a harness's own subagents are not what the
    workflow declared.
    """
    if intent.call.target_harness is None:
        return None
    return DelegationAttempt(
        delegate_id=intent.child_invocation_id,
        target_harness=intent.call.target_harness,
        outcome=_OUTCOMES.get(intent.status) if intent.status is not None else None,
        exit_code=intent.exit_code,
        reason=intent.reason,
    )


class ChildJournalDelegations:
    """`DelegationEvidencePort` over the phase workspace's child journal."""

    async def attempts(self, workspace: ManagedWorkspace) -> tuple[DelegationAttempt, ...]:
        execute = _exec_fn_for(workspace)
        located = await execute(
            "printf '%s/.agentic-session-store/%s/children.sqlite' "
            f'"${shlex.quote(ENV_AGENTIC_SESSION_STORE_SPOOL)}" '
            f'"${shlex.quote(ENV_AGENTIC_SESSION_STORE_PARTITION)}"',
            timeout=15,
        )
        path = located.stdout.strip()
        if located.exit_code != 0 or "//" in path or not path.startswith("/"):
            raise DelegationEvidenceUnavailableError(
                "the workspace has no session store partition, so no child journal"
            )
        reader = WorkspaceChildJournalReader(execute, path)
        attempts: list[DelegationAttempt] = []
        after = 0
        try:
            while True:
                page = await reader.page(after)
                for change in page.changes:
                    attempt = delegation_attempt(change.intent)
                    if attempt is not None:
                        attempts.append(attempt)
                if page.next_after is None:
                    break
                after = page.next_after
        except (JournalReadError, ValueError) as error:
            raise DelegationEvidenceUnavailableError(str(error)) from error
        return tuple(attempts)
