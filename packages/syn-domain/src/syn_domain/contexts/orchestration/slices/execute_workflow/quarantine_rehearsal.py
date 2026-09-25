"""Credential and connectivity rehearsal for quarantine pushes (#1393, #1396)."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from syn_domain.contexts.orchestration.slices.execute_workflow.errors import (
    QuarantinePathUnusableError,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.workspace_git import (
    GitWorkspace,
    answered,
    git,
    push,
    repositories,
)

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
        ExecutionResult,
    )


async def run_quarantine_rehearsal(
    workspace: GitWorkspace,
    *,
    phase_id: str,
    ref: str,
    attempts: int,
    retry_seconds: float,
) -> None:
    """Confirm a credential reaches origin without promising update acceptance."""
    repos = await repositories(workspace)
    if not repos:
        return
    await _renew_credential(
        workspace, phase_id=phase_id, attempts=attempts, retry_seconds=retry_seconds
    )

    unanswered: list[str] = []
    for repo in repos:
        head = (await git(workspace, repo, "rev-parse", "--revs-only", "HEAD")).strip()
        if not head:
            continue
        rehearsed = await _push(
            workspace,
            repo,
            commit=head,
            ref=ref,
            attempts=attempts,
            retry_seconds=retry_seconds,
        )
        if rehearsed.exit_code == 0:
            continue
        if not answered(rehearsed):
            unanswered.append(repo)
            continue
        raise QuarantinePathUnusableError(
            phase_id=phase_id,
            detail=(
                f"A rehearsal push of {repo} to {ref} was refused by origin: "
                f"{(rehearsed.stderr or rehearsed.stdout).strip() or 'no output'}"
            ),
        )

    if unanswered:
        logger.warning(
            "Phase %s is starting UNREHEARSED: origin never answered a rehearsal push "
            "of %s within the bound, after %d attempts. A failed teardown push will "
            "report the work NOT RECOVERABLE (#1396).",
            phase_id,
            ", ".join(unanswered),
            attempts,
        )
        return
    logger.info(
        "Phase %s holds a credential that reaches origin for %s. Server-side update "
        "acceptance is not covered by this rehearsal (#1396).",
        phase_id,
        ref,
    )


async def _renew_credential(
    workspace: GitWorkspace, *, phase_id: str, attempts: int, retry_seconds: float
) -> None:
    """Retry renewal, then retain the freshly provisioned credential on failure."""
    for attempt in range(1, attempts + 1):
        try:
            await workspace.renew_git_credential()
            return
        except asyncio.CancelledError:
            raise
        except Exception as unrenewable:
            if attempt < attempts:
                logger.info(
                    "Could not mint a fresh git credential for phase %s "
                    "(attempt %d of %d): %s. Retrying in %.0fs.",
                    phase_id,
                    attempt,
                    attempts,
                    unrenewable,
                    retry_seconds,
                )
                await asyncio.sleep(retry_seconds)
                continue
            logger.warning(
                "Could not mint a fresh git credential for phase %s after %d attempts: "
                "%s. Keeping the credential provisioned with the workspace (#1396).",
                phase_id,
                attempts,
                unrenewable,
            )


async def _push(
    workspace: GitWorkspace,
    repo: str,
    *,
    commit: str,
    ref: str,
    attempts: int,
    retry_seconds: float,
) -> ExecutionResult:
    """Retry the dry-run push and return its final observed result."""
    for attempt in range(1, attempts + 1):
        rehearsed = await push(workspace, repo, commit=commit, ref=ref, dry_run=True)
        if rehearsed.exit_code == 0 or attempt == attempts:
            return rehearsed
        logger.info(
            "A rehearsal push of %s to %s failed (attempt %d of %d): %s. Retrying in %.0fs.",
            repo,
            ref,
            attempt,
            attempts,
            (rehearsed.stderr or rehearsed.stdout).strip() or "no output",
            retry_seconds,
        )
        await asyncio.sleep(retry_seconds)
    raise AssertionError("rehearsal retry loop exhausted without a result")
