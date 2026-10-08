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
    from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
        ExecutionResult,
    )

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
#: finish is killed at its deadline. Only after the timed-out installer is
#: reaped inside the container (`_reap_timed_out_install`): idempotency makes a
#: SEQUENTIAL re-run safe, not two concurrent ones. One retry bounds what a
#: genuinely hung installer costs to two deadlines.
_SKILL_INSTALL_RETRY_BACKOFF_SECONDS: Final[tuple[float, ...]] = (0.5, 1.0, 2.0)

#: This repo's "no real status" sentinel (timeout, missing container), which is
#: NOT a signal death and must not be retried as one.
_NO_STATUS_SENTINEL: Final = -1

#: Attempts a timed-out install gets in total (PC-126).
_TIMEOUT_ATTEMPTS: Final = 2

#: Every signal retry plus every timeout attempt, plus the final attempt: the
#: finite bound on `skills add` calls for one skill.
_MAX_ATTEMPTS: Final = len(_SKILL_INSTALL_RETRY_BACKOFF_SECONDS) + _TIMEOUT_ATTEMPTS + 1


#: Kills every process in the workspace still running THIS `skills add`, then
#: waits (up to 5s) until none is left. The needle is the argv TAIL, not
#: `skills add`, because the CLI is a node script: its process is
#: `node <path-to-cli> add SRC --agent KEY -y`, and killing only the `sh -c`
#: wrapper would orphan it. `$1`/`$2` are the source and agent, so the needle
#: never appears contiguously in this script's own command line.
_REAP_SCRIPT: Final = """needle=" add $1 --agent $2 -y"
found() {
  for d in /proc/[0-9]*; do
    cmd=$(tr '\\0' ' ' < "$d/cmdline" 2>/dev/null) || continue
    case "$cmd" in *"$needle"*) echo "${d#/proc/}" ;; esac
  done
}
for pid in $(found); do kill -9 "$pid" 2>/dev/null; done
i=0
while [ -n "$(found)" ]; do
  i=$((i + 1)); [ "$i" -ge 50 ] && exit 1; sleep 0.1
done
"""

#: Deadline for the reap itself; it reads /proc and kills, nothing more.
_REAP_TIMEOUT_SECONDS: Final = 30


async def _reap_timed_out_install(workspace: ManagedWorkspace, source: str, agent_key: str) -> bool:
    """Kill a timed-out `skills add` still running in the container (PC-126).

    The deadline kills the `docker exec` CLIENT, not the installer inside the
    container, so without this the retry runs BESIDE the first attempt. That is
    not safe: the installer (skills 1.5.14 `cleanAndCreateDirectory`) deletes
    its destination recursively before copying, so a first attempt that wakes
    after the retry succeeded removes the files the agent is about to read.
    Sequential idempotency says nothing about two concurrent writers. True when
    no such process is left; False means the retry must not run.
    """
    result = await workspace.execute(
        ["sh", "-c", _REAP_SCRIPT, "sh", source, agent_key],
        timeout_seconds=_REAP_TIMEOUT_SECONDS,
    )
    return result.exit_code == 0


def _backoff(attempt: int) -> float:
    """The wait after the ``attempt``-th call, holding at the longest once they run out."""
    waits = _SKILL_INSTALL_RETRY_BACKOFF_SECONDS
    return waits[min(attempt, len(waits)) - 1]


def _is_local_signal_death(exit_code: int, timed_out: bool) -> bool:
    """True when the API's spawned child was killed by a signal (#1046)."""
    return exit_code < 0 and exit_code != _NO_STATUS_SENTINEL and not timed_out


def _is_retryable(result: ExecutionResult, timeouts: int, signal_deaths: int) -> bool:
    """Whether this failure still has a retry left in ITS OWN allowance (PC-126).

    The two allowances are separate so that signal deaths spent before a
    timeout cannot use up the timeout's one retry, and the reverse.
    """
    if result.timed_out:
        return timeouts < _TIMEOUT_ATTEMPTS
    if _is_local_signal_death(result.exit_code, result.timed_out):
        return signal_deaths <= len(_SKILL_INSTALL_RETRY_BACKOFF_SECONDS)
    return False


def _failure(
    result: ExecutionResult, skill_name: str, agent_key: str, timeout_seconds: int, timeouts: int
) -> Exception:
    """How the install ended: a transient timeout, or the installer's own failure."""
    failed = SkillInstallFailed.after_exit(
        skill_name,
        agent_key,
        exit_code=result.exit_code,
        output=result.stderr or result.stdout or "",
        timed_out=result.timed_out,
    )
    if not result.timed_out:
        return failed
    return ProvisionStepTimeoutError(
        ProvisionStep.SKILL_INSTALL,
        subject=f"skill {skill_name!r} for agent {agent_key!r}",
        timeout_seconds=timeout_seconds,
        attempts=timeouts,
        detail=str(failed),
    )


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
    timeouts = 0
    signal_deaths = 0
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        result = await workspace.execute(
            ["skills", "add", source, "--agent", agent_key, "-y"],
            timeout_seconds=timeout_seconds,
            working_directory="/workspace",
        )
        if result.exit_code == 0:
            return
        timeouts += 1 if result.timed_out else 0
        signal_deaths += 0 if result.timed_out else 1
        if not _is_retryable(result, timeouts, signal_deaths) or (
            result.timed_out and not await _reap_timed_out_install(workspace, source, agent_key)
        ):
            raise _failure(result, skill_name, agent_key, timeout_seconds, timeouts)
        logger.warning(
            "installing skill %r: %s (exit %d), retry %d/%d (#1046, PC-126)",
            skill_name,
            f"timed out after {timeout_seconds}s" if result.timed_out else "spawned child died",
            result.exit_code,
            attempt,
            _MAX_ATTEMPTS - 1,
        )
        await asyncio.sleep(_backoff(attempt))
    raise AssertionError("unreachable: every allowance is exhausted within _MAX_ATTEMPTS")
