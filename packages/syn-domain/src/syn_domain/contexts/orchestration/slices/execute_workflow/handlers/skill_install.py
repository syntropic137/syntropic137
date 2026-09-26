"""Install one skill into a workspace, surviving a spawn that dies on a signal (#1046)."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Final

from syn_domain.contexts.orchestration._shared.skill_errors import SkillInstallFailed

if TYPE_CHECKING:
    from syn_adapters.workspace_backends.service.managed_workspace import ManagedWorkspace

logger = logging.getLogger(__name__)

SKILL_INSTALL_TIMEOUT_SECONDS: Final = 120

#: Waits BETWEEN attempts of one `skills add`, so there is one more attempt
#: than there are entries. Only a local signal death is retried (#1046): a
#: negative status means the API's own spawned child was killed by a signal,
#: so the install very likely never ran, and `skills add -y` is idempotent if
#: it did. The root cause (grpc fork handlers under uvloop's fork()) is fixed
#: by GRPC_ENABLE_FORK_SUPPORT=false in the syn-api image; this is the backstop.
#: A positive exit is the installer refusing, and still fails fast.
_SKILL_INSTALL_RETRY_BACKOFF_SECONDS: Final[tuple[float, ...]] = (0.5, 1.0, 2.0)

#: This repo's "no real status" sentinel (timeout, missing container), which is
#: NOT a signal death and must not be retried as one.
_NO_STATUS_SENTINEL: Final = -1


def _is_local_signal_death(exit_code: int, timed_out: bool) -> bool:
    """True when the API's spawned child was killed by a signal (#1046)."""
    return exit_code < 0 and exit_code != _NO_STATUS_SENTINEL and not timed_out


async def install_skill(
    workspace: ManagedWorkspace, skill_name: str, source: str, agent_key: str
) -> None:
    """Run `skills add` for one skill, retrying only a local signal death.

    The spawned `docker exec` child could die of SIGSEGV before exec (#1046,
    #1295). Every exec rolls that dice, so without a retry a phase that
    declares N skills fails N times as often as one that declares one.
    """
    attempts = len(_SKILL_INSTALL_RETRY_BACKOFF_SECONDS) + 1
    for attempt in range(1, attempts + 1):
        result = await workspace.execute(
            ["skills", "add", source, "--agent", agent_key, "-y"],
            timeout_seconds=SKILL_INSTALL_TIMEOUT_SECONDS,
            working_directory="/workspace",
        )
        if result.exit_code == 0:
            return
        if attempt < attempts and _is_local_signal_death(result.exit_code, result.timed_out):
            logger.warning(
                "installing skill %r: spawned child died (exit %d), retry %d/%d (#1046)",
                skill_name,
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
