"""Install one skill into a workspace, surviving a spawn that dies on a signal (#1046)."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Final

from syn_domain.contexts.orchestration._shared.skill_errors import SkillInstallFailed
from syn_domain.contexts.orchestration.slices.execute_workflow.errors import (
    ProvisionStep,
    ProvisionStepTimeoutError,
)
from syn_shared.settings import get_settings

if TYPE_CHECKING:
    from syn_adapters.workspace_backends.service.managed_workspace import ManagedWorkspace

logger = logging.getLogger(__name__)

#: Waits BETWEEN attempts of one `skills add`, so there is one more attempt
#: than there are entries. Only a local signal death is retried (#1046): a
#: negative status means the API's own spawned child was killed by a signal.
#: That is ambiguous about whether the install ran, so the retry relies on
#: `skills add -y` being idempotent: verified against skills 1.5.14 in the
#: workspace image (two runs exit 0, one identical SKILL.md). Re-verify on a
#: skills pin bump. The root cause (grpc fork handlers under uvloop's fork()) is fixed
#: by GRPC_ENABLE_FORK_SUPPORT=false in the syn-api image; this is the backstop.
#: A positive exit is the installer refusing, and still fails fast.
#: A timeout is retried ONCE (PC-126): under host load an install that would
#: finish is killed at its deadline. The same idempotency makes that safe, and
#: one retry bounds what a genuinely hung installer costs to two deadlines.
_SKILL_INSTALL_RETRY_BACKOFF_SECONDS: Final[tuple[float, ...]] = (0.5, 1.0, 2.0)

#: This repo's "no real status" sentinel (timeout, missing container), which is
#: NOT a signal death and must not be retried as one.
_NO_STATUS_SENTINEL: Final = -1

#: Attempts a timed-out install gets in total (PC-126).
_TIMEOUT_ATTEMPTS: Final = 2


def _is_local_signal_death(exit_code: int, timed_out: bool) -> bool:
    """True when the API's spawned child was killed by a signal (#1046)."""
    return exit_code < 0 and exit_code != _NO_STATUS_SENTINEL and not timed_out


async def install_skill(
    workspace: ManagedWorkspace, skill_name: str, source: str, agent_key: str
) -> None:
    """Run `skills add` for one skill, retrying a local signal death or one timeout.

    The spawned `docker exec` child could die of SIGSEGV before exec (#1046,
    #1295). Every exec rolls that dice, so without a retry a phase that
    declares N skills fails N times as often as one that declares one.
    A timeout that survives its retry raises `ProvisionStepTimeoutError`,
    which records the run as transient and resumable rather than broken.
    """
    timeout_seconds = get_settings().skill_install_timeout_seconds
    attempts = len(_SKILL_INSTALL_RETRY_BACKOFF_SECONDS) + 1
    timeouts = 0
    for attempt in range(1, attempts + 1):
        result = await workspace.execute(
            ["skills", "add", source, "--agent", agent_key, "-y"],
            timeout_seconds=timeout_seconds,
            working_directory="/workspace",
        )
        if result.exit_code == 0:
            return
        if result.timed_out:
            timeouts += 1
        if result.timed_out and (timeouts >= _TIMEOUT_ATTEMPTS or attempt == attempts):
            raise ProvisionStepTimeoutError(
                ProvisionStep.SKILL_INSTALL,
                subject=f"skill {skill_name!r} for agent {agent_key!r}",
                timeout_seconds=timeout_seconds,
                attempts=timeouts,
            )
        retryable = result.timed_out or _is_local_signal_death(result.exit_code, result.timed_out)
        if attempt < attempts and retryable:
            logger.warning(
                "installing skill %r: %s (exit %d), retry %d/%d (#1046, PC-126)",
                skill_name,
                f"timed out after {timeout_seconds}s" if result.timed_out else "spawned child died",
                result.exit_code,
                attempt,
                attempts - 1,
            )
            await asyncio.sleep(_SKILL_INSTALL_RETRY_BACKOFF_SECONDS[attempt - 1])
            continue
        raise SkillInstallFailed.after_exit(
            skill_name,
            agent_key,
            exit_code=result.exit_code,
            output=result.stderr or result.stdout or "",
            timed_out=result.timed_out,
        )
