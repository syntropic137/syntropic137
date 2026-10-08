"""Setup phase execution logic for ManagedWorkspace (ADR-024).

Extracted from ManagedWorkspace to reduce class complexity.
Contains the setup phase runner and secrets cleanup logic.

The setup phase:
1. Runs the setup script with secrets provided via process-scoped env vars
2. Cleans up shell history and other artifacts that might contain secrets
3. Removes any temporary files and setup artifacts used during the setup phase

After the setup phase completes, the agent phase can safely run
without access to raw secrets or setup-time artifacts that may contain them.

See ADR-024: Secure Token Architecture
"""

from __future__ import annotations

import asyncio
import logging
from enum import StrEnum
from typing import TYPE_CHECKING, Final, NamedTuple

from syn_adapters.workspace_backends.exec_status_lost import is_status_lost
from syn_domain.contexts.orchestration import ProvisionStep, ProvisionStepTimeoutError
from syn_shared.display import format_exit_code
from syn_shared.env_constants import (
    ENV_ANTHROPIC_API_KEY,
    ENV_CLAUDE_CODE_OAUTH_TOKEN,
    ENV_GIT_AUTHOR_EMAIL,
    ENV_GIT_AUTHOR_NAME,
    ENV_GIT_COMMITTER_EMAIL,
    ENV_GIT_COMMITTER_NAME,
)
from syn_shared.settings import get_settings

if TYPE_CHECKING:
    from syn_adapters.workspace_backends.service.managed_workspace import ManagedWorkspace
    from syn_adapters.workspace_backends.service.setup_phase_secrets import SetupPhaseSecrets
    from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
        ExecutionResult,
    )

logger = logging.getLogger(__name__)


def _build_setup_env(secrets: SetupPhaseSecrets) -> dict[str, str]:
    """Build environment dict from secrets for the setup phase.

    Args:
        secrets: Secrets to make available during setup

    Returns:
        Environment variable dict
    """
    setup_env: dict[str, str] = {}

    # GitHub tokens are now embedded in the setup script by build_setup_script()
    # (per-repo entries in ~/.git-credentials — ADR-058). No env var needed.

    if secrets.claude_code_oauth_token:
        setup_env[ENV_CLAUDE_CODE_OAUTH_TOKEN] = secrets.claude_code_oauth_token

    if secrets.anthropic_api_key:
        setup_env[ENV_ANTHROPIC_API_KEY] = secrets.anthropic_api_key

    # Git identity from GitHub App bot configuration.
    # Both author and committer are set explicitly -- entrypoint.sh would derive
    # committer from author if omitted, but we set both for clarity.
    if secrets.git_author_name:
        setup_env[ENV_GIT_AUTHOR_NAME] = secrets.git_author_name
        setup_env[ENV_GIT_COMMITTER_NAME] = secrets.git_author_name
    if secrets.git_author_email:
        setup_env[ENV_GIT_AUTHOR_EMAIL] = secrets.git_author_email
        setup_env[ENV_GIT_COMMITTER_EMAIL] = secrets.git_author_email

    return setup_env


async def run_setup_phase(
    workspace: object,
    secrets: SetupPhaseSecrets,
    setup_script: str | None = None,
) -> ExecutionResult:
    """Run setup phase with secrets, then clear secrets (ADR-024).

    This function:
    1. Runs the setup script with secrets available as env vars
    2. Clears all secrets from the container environment
    3. Removes any temporary files that might contain secrets

    After this completes, the agent phase can safely run
    without access to raw secrets.

    Args:
        workspace: ManagedWorkspace instance (typed as object to avoid circular import)
        secrets: Secrets to make available during setup
        setup_script: Custom setup script override (uses secrets.build_setup_script() if None)

    Returns:
        ExecutionResult from setup script
    """
    from syn_adapters.workspace_backends.service.managed_workspace import ManagedWorkspace

    ws = workspace
    if not isinstance(ws, ManagedWorkspace):
        raise TypeError(f"Expected ManagedWorkspace, got {type(ws).__name__}")

    setup_env = _build_setup_env(secrets)

    # Write setup script to container
    script = setup_script or secrets.build_setup_script()
    await ws.inject_files(
        [(".setup/setup.sh", script.encode())],
        base_path="/workspace",
    )

    result: ExecutionResult | None = None
    try:
        result = await _run_setup_script(ws, secrets, script, setup_env)

        if result.exit_code != 0:
            # Names the ADR-024 step, not "the setup phase": a workflow phase of
            # a similar name runs alongside it and reading one as the other sent
            # an operator to a phase that had completed (#1236).
            logger.error(
                "Secret-injection setup failed (workspace=%s, exit=%s): %s",
                ws.workspace_id,
                format_exit_code(result.exit_code),
                result.stderr,
            )

        return result
    finally:
        try:
            await clear_secrets(ws)
        finally:
            # Runs even if clear_secrets raised. Fail-closed: guarantee no codex
            # credential lingers under /workspace, or raise a security failure.
            if secrets.codex_auth_json:
                await _assert_codex_credential_removed(ws, setup_result=result)
        logger.info(
            "Secret-injection setup complete, transient material cleared (workspace=%s)",
            ws.workspace_id,
        )


#: One retry, and only of an exec whose status was LOST (no status, no output,
#: no timeout - see `exec_status_lost`). The script is written to be re-run
#: (every clone is `[ -d ]`-guarded, credential files are replaced, #1393),
#: so a second run costs seconds, where giving up discarded the whole execution: four
#: verify/reverify phases on 2026-10-06/07 ended this way while the script
#: itself had very likely finished. A status that WAS reported - any exit
#: code, a timeout - is an answer and is never retried.
#:
#: A timeout stays unretried on purpose (PC-126 weighed it): a clone killed
#: mid-transfer leaves its destination behind, the re-run's `[ -d ]` guard
#: skips it, and the phase would continue on a broken checkout. The caller
#: records a timeout as a transient `ProvisionStepTimeoutError` instead, and a
#: resume provisions a fresh workspace - the retry without that hazard.
_SETUP_ATTEMPTS: Final = 2
_SETUP_RETRY_BACKOFF_SECONDS: Final = 1.0


async def _run_setup_script(
    ws: ManagedWorkspace,
    secrets: SetupPhaseSecrets,
    script: str,
    setup_env: dict[str, str],
) -> ExecutionResult:
    """Run the setup script, once more if the first run's status was lost."""
    from syn_shared.settings import get_settings

    for attempt in range(1, _SETUP_ATTEMPTS + 1):
        if attempt > 1:
            # Restage both: the first run may have got as far as relocating
            # and removing the staged codex credential.
            await ws.inject_files([(".setup/setup.sh", script.encode())], base_path="/workspace")
        # Stage the codex auth file INSIDE the caller's try so its finally-block
        # cleanup always runs even if this injection raises. The docker copy
        # path IGNORES base_path (it always writes under the /workspace mount),
        # so we cannot inject straight to ~/.codex; we stage it under .setup/
        # and the setup script (SetupPhaseSecrets._append_codex_auth) relocates
        # it to ~/.codex/auth.json (0600) and removes the staged copy. The
        # secret contents never appear in the setup script text.
        if secrets.codex_auth_json:
            await ws.inject_files(
                [(".setup/codex-auth.json", secrets.codex_auth_json.encode())],
                base_path="/workspace",
            )

        logger.info(
            "Running secret-injection setup script (workspace=%s, attempt=%d/%d)",
            ws.workspace_id,
            attempt,
            _SETUP_ATTEMPTS,
        )
        result = await ws.execute(
            ["bash", "/workspace/.setup/setup.sh"],
            environment=setup_env,
            timeout_seconds=get_settings().setup_phase_timeout_seconds,
        )
        if not is_status_lost(result) or attempt == _SETUP_ATTEMPTS:
            return result
        logger.warning(
            "Secret-injection setup returned no status (workspace=%s, attempt=%d/%d); "
            "re-running it: %s",
            ws.workspace_id,
            attempt,
            _SETUP_ATTEMPTS,
            result.stderr,
        )
        await asyncio.sleep(_SETUP_RETRY_BACKOFF_SECONDS)
    raise AssertionError("unreachable: the last attempt always returns")


_CODEX_STAGED_AUTH = "/workspace/.setup/codex-auth.json"


class _CredentialState(StrEnum):
    """What the probe established, kept distinct from how it failed.

    ABSENT and "could not tell" MUST NOT share a channel. They did: the guard
    read `exit_code != 0` as "gone", which also swallowed a timeout, a provider
    error and a missing workspace - every way of failing to look became
    evidence of absence.
    """

    PRESENT = "present"
    ABSENT = "absent"
    UNVERIFIABLE = "unverifiable"
    #: Unverifiable because the probe ran out of time (PC-126): retried like
    #: UNVERIFIABLE, and the only kind whose exhaustion is a loaded host.
    TIMED_OUT = "timed_out"


#: Reported on stdout so presence is proven by OUTPUT, not by a status that
#: several unrelated failures also produce.
_PRESENT_MARKER = "STAGED_CREDENTIAL_PRESENT"
_ABSENT_MARKER = "STAGED_CREDENTIAL_ABSENT"


def _exec_timeout_seconds() -> int:
    """The bound on one guard exec: ``CREDENTIAL_GUARD_EXEC_TIMEOUT_SECONDS`` (PC-126).

    Long enough for a `[ -e ]` or an `rm` in a container on a loaded host;
    short enough that a wedged one does not hold the setup phase open. ONE
    expiry of it decides nothing (#1293); every expiry is a loaded host.
    """
    return get_settings().credential_guard_exec_timeout_seconds


#: Waits BETWEEN attempts, so there is one more attempt than there are entries.
#: An exec that did not answer has not established anything, and treating the
#: first such stall as a confirmed failure discarded whole executions mid-run
#: (#1293: exec-b8221f1169d9, $3.70, phase 1 of 3, identical retry succeeded).
#: Bounded, and deliberately small: a workspace that cannot answer in ~23s of
#: trying still fails closed, it just no longer fails on one stumble.
_RETRY_BACKOFF_SECONDS: Final[tuple[float, ...]] = (0.5, 1.0, 2.0)
_MAX_ATTEMPTS: Final = len(_RETRY_BACKOFF_SECONDS) + 1


class _GuardOutcome(NamedTuple):
    """Whether a guarded step established what it needed, and what it saw trying.

    The record is the point. "unable to confirm removal" with nothing else in
    it is fatal without being diagnosable, so every attempt is carried out of
    the retry loop and into the error the operator reads.
    """

    succeeded: bool
    attempts: tuple[str, ...]
    #: Every failed attempt ran out of time: the guard established nothing
    #: either way, and a loaded host is the explanation (PC-126).
    all_timed_out: bool = False

    def report(self) -> str:
        return (
            f"attempts={len(self.attempts)} ["
            + ", ".join(f"#{i} {seen}" for i, seen in enumerate(self.attempts, 1))
            + "]"
        )


#: Bound on the diagnosis quoted per attempt, so four attempts stay readable.
_ATTEMPT_DETAIL_CHARS: Final = 400


def _attempt_record(result: ExecutionResult) -> str:
    """One attempt, as the operator reads it in the fail-closed error.

    A lost status carries its diagnosis (container state, timing against the
    deadline). Without it, four attempts read "exit=-1 (no exit status)" four
    times and the run ended with nothing to act on (exec-ff7e0c990b00).
    """
    record = f"exit={format_exit_code(result.exit_code)}"
    if result.timed_out:
        return record + f" (timed out after {_exec_timeout_seconds()}s)"
    if is_status_lost(result):
        record += f" ({result.stderr[:_ATTEMPT_DETAIL_CHARS]})"
    return record


async def _wait_before_retry(attempt: int) -> None:
    """Back off between attempts; no wait after the last one."""
    if attempt < _MAX_ATTEMPTS:
        await asyncio.sleep(_RETRY_BACKOFF_SECONDS[attempt - 1])


async def _staged_credential_state(ws: ManagedWorkspace) -> _CredentialState:
    """Advisory: does the staged credential appear to exist?

    ADVISORY, not authoritative, and the distinction matters. `[ -e PATH ]` is
    false both when the path is absent AND when it cannot be inspected - a
    directory whose traversal is denied answers "no" indistinguishably from an
    empty one. So a report of ABSENT is not proof of absence. What proves it is
    the removal below, whose exit status separates "gone" from "could not touch
    it". This exists to say something useful in the log, and to catch a
    credential that is still readable.
    """
    probe = await ws.execute(
        [
            "sh",
            "-c",
            f"if [ -e {_CODEX_STAGED_AUTH} ]; then echo {_PRESENT_MARKER}; "
            f"else echo {_ABSENT_MARKER}; fi",
        ],
        timeout_seconds=_exec_timeout_seconds(),
    )

    if probe.timed_out:
        logger.error(
            "SECURITY: staged codex credential probe timed out (workspace=%s)",
            ws.workspace_id,
        )
        return _CredentialState.TIMED_OUT
    if probe.exit_code != 0:
        logger.error(
            "SECURITY: could not determine whether a staged codex credential "
            "remains (workspace=%s, exit=%s): %s",
            ws.workspace_id,
            format_exit_code(probe.exit_code),
            probe.stderr,
        )
        return _CredentialState.UNVERIFIABLE

    # EXACT match on the last line, not endswith: `endswith` would accept
    # "NOT_STAGED_CREDENTIAL_ABSENT", which contradicts the rule that output we
    # do not recognise is UNVERIFIABLE.
    lines = (probe.stdout or "").strip().splitlines()
    last = lines[-1].strip() if lines else ""
    if last == _ABSENT_MARKER:
        return _CredentialState.ABSENT
    if last == _PRESENT_MARKER:
        return _CredentialState.PRESENT

    logger.error(
        "SECURITY: unrecognised staged-credential probe output (workspace=%s): %r",
        ws.workspace_id,
        last,
    )
    return _CredentialState.UNVERIFIABLE


async def _remove_staged_credential(ws: ManagedWorkspace) -> _GuardOutcome:
    """Force-remove the staged credential, retrying a removal that could not run.

    `rm -f` is idempotent, so repeating it risks nothing, and retrying cannot
    launder a genuine refusal into success: permission denied is still denied
    on the fourth attempt. What it survives is a container that stalled for a
    moment, which is otherwise indistinguishable here from one that refused.
    """
    attempts: list[str] = []
    timeouts = 0
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        removal = await ws.execute(
            ["rm", "-f", "--", _CODEX_STAGED_AUTH],
            timeout_seconds=_exec_timeout_seconds(),
        )
        attempts.append(_attempt_record(removal))
        timeouts += 1 if removal.timed_out else 0
        if removal.exit_code == 0:
            return _GuardOutcome(succeeded=True, attempts=tuple(attempts))
        logger.warning(
            "SECURITY: staged codex credential removal did not succeed "
            "(workspace=%s, attempt=%d/%d, exit=%s): %s",
            ws.workspace_id,
            attempt,
            _MAX_ATTEMPTS,
            format_exit_code(removal.exit_code),
            removal.stderr,
        )
        await _wait_before_retry(attempt)

    return _GuardOutcome(
        succeeded=False, attempts=tuple(attempts), all_timed_out=timeouts == len(attempts)
    )


async def _recheck_staged_credential_gone(ws: ManagedWorkspace) -> _GuardOutcome:
    """Confirm the credential is gone, retrying ONLY a probe that did not answer.

    The retry is scoped by what the probe established, not by whether we liked
    the answer:

    - ABSENT answers, and confirms. Done.
    - PRESENT answers too. The credential survived a removal that reported
      success, which is a fault to report AT ONCE - never something to probe
      again in the hope a later attempt says something nicer. Retrying this
      would be the one thing that turns a guard into a coin flip, so it
      returns immediately, failed, after a single attempt.
    - UNVERIFIABLE - a stall, a provider error, output we cannot parse -
      establishes nothing at all, and is the only state worth another look
      (#1293).

    Exhausting the attempts still fails: silence is not clearance.
    """
    attempts: list[str] = []
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        state = await _staged_credential_state(ws)
        attempts.append(state.value)
        if state not in (_CredentialState.UNVERIFIABLE, _CredentialState.TIMED_OUT):
            return _GuardOutcome(
                succeeded=state is _CredentialState.ABSENT,
                attempts=tuple(attempts),
            )
        logger.warning(
            "SECURITY: staged codex credential recheck did not answer "
            "(workspace=%s, attempt=%d/%d); retrying",
            ws.workspace_id,
            attempt,
            _MAX_ATTEMPTS,
        )
        await _wait_before_retry(attempt)

    timed_out = _CredentialState.TIMED_OUT.value
    return _GuardOutcome(
        succeeded=False,
        attempts=tuple(attempts),
        all_timed_out=all(seen == timed_out for seen in attempts),
    )


def _guard_failure(
    message: str, outcome: _GuardOutcome, setup_result: ExecutionResult | None
) -> Exception:
    """The fail-closed error, transient only when every attempt timed out (PC-126).

    Either way the agent is NOT launched: this only decides how the run is
    recorded. A confirmed presence or a refusal is a fault, not a loaded host,
    so it stays a plain `RuntimeError`. The setup script's own outcome is
    quoted, because this error replaces it on the way out of `finally`.
    """
    if setup_result is not None and setup_result.exit_code != 0:
        how = "timed out" if setup_result.timed_out else format_exit_code(setup_result.exit_code)
        message += f"; the setup script itself had already failed first ({how})"
    if not outcome.all_timed_out:
        return RuntimeError(message)
    return ProvisionStepTimeoutError(
        ProvisionStep.SECRET_INJECTION,
        subject="staged codex credential cleanup",
        timeout_seconds=_exec_timeout_seconds(),
        attempts=len(outcome.attempts),
        detail=message,
    )


async def _assert_codex_credential_removed(
    ws: ManagedWorkspace, *, setup_result: ExecutionResult | None = None
) -> None:
    """Guarantee no staged codex credential lingers under /workspace, or raise.

    ``clear_secrets`` removes /workspace/.setup, but if that cleanup failed the
    staged ``codex-auth.json`` could remain readable by the agent.

    FAILS CLOSED. The removal runs unconditionally and its exit status is the
    authority: `rm -f` returns 0 for a path that is already gone and nonzero
    when it cannot act - permission denied, an untraversable parent - which is
    exactly the case a `[ -e ]` probe reports as "absent". Removing without
    asking first costs one exec and removes a whole class of false clearance.

    Both steps are bounded-retried, and neither retry relaxes the verdict: what
    is retried is an exec that did NOT answer, which had been counted as an
    answer meaning "no" (#1293). An answer of "still present" fails on the spot.
    """
    if await _staged_credential_state(ws) is _CredentialState.PRESENT:
        logger.error(
            "SECURITY: staged codex credential still present under /workspace "
            "after cleanup (workspace=%s); force-removing",
            ws.workspace_id,
        )

    removal = await _remove_staged_credential(ws)
    if not removal.succeeded:
        # Previously unchecked, and then checked once. Without this, a removal
        # that could not run left the credential in place and the guard went on
        # to trust a recheck that cannot distinguish absence from
        # inaccessibility.
        msg = (
            f"SECURITY: unable to remove staged codex credential "
            f"{_CODEX_STAGED_AUTH} (workspace={ws.workspace_id}, "
            f"{removal.report()})"
        )
        raise _guard_failure(msg, removal, setup_result)

    recheck = await _recheck_staged_credential_gone(ws)
    if not recheck.succeeded:
        # Not `is PRESENT`: an UNVERIFIABLE recheck has not shown the
        # credential is gone, and accepting it is the same fail-open this
        # function exists to prevent. The report says which of the two it was,
        # and how many looks it took, because "unable to confirm" on its own
        # ends a run without telling anyone why.
        msg = (
            f"SECURITY: unable to confirm removal of staged codex credential "
            f"{_CODEX_STAGED_AUTH} (workspace={ws.workspace_id}, "
            f"{recheck.report()})"
        )
        raise _guard_failure(msg, recheck, setup_result)


async def clear_secrets(workspace: object) -> None:
    """Clear all traces of secrets from the container.

    This is called after setup phase completes. It removes:
    - Environment variables containing secrets
    - Shell history
    - Temporary files

    Note: Git credentials in ~/.git-credentials are intentionally kept
    so the agent can push without raw token access.

    Args:
        workspace: ManagedWorkspace instance (typed as object to avoid circular import)
    """
    from syn_adapters.workspace_backends.service.managed_workspace import ManagedWorkspace

    ws = workspace
    if not isinstance(ws, ManagedWorkspace):
        raise TypeError(f"Expected ManagedWorkspace, got {type(ws).__name__}")

    # Clear shell history and temp files
    clear_script = """#!/bin/bash
# Clear shell history
rm -f ~/.bash_history ~/.zsh_history /root/.bash_history /root/.zsh_history 2>/dev/null || true

# Clear setup script (contains no secrets, but clean up)
rm -rf /workspace/.setup 2>/dev/null || true

# Clear any temp files
rm -rf /tmp/secrets* /tmp/setup* 2>/dev/null || true

# Note: ~/.git-credentials is kept intentionally for git push
"""
    await ws.inject_files(
        [(".cleanup/clear.sh", clear_script.encode())],
        base_path="/workspace",
    )
    cleanup = await ws.execute(
        ["bash", "/workspace/.cleanup/clear.sh"],
        timeout_seconds=2 * _exec_timeout_seconds(),
    )
    if cleanup.exit_code != 0:
        logger.warning(
            "Secret cleanup script exited non-zero (exit=%s, workspace=%s): %s",
            format_exit_code(cleanup.exit_code),
            ws.workspace_id,
            cleanup.stderr,
        )

    # Clean up the cleanup script too
    await ws.execute(
        ["rm", "-rf", "/workspace/.cleanup"],
        timeout_seconds=_exec_timeout_seconds(),
    )
