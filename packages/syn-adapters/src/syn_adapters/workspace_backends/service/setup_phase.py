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

import logging
from enum import StrEnum
from typing import TYPE_CHECKING

from syn_shared.env_constants import (
    ENV_ANTHROPIC_API_KEY,
    ENV_CLAUDE_CODE_OAUTH_TOKEN,
    ENV_GIT_AUTHOR_EMAIL,
    ENV_GIT_AUTHOR_NAME,
    ENV_GIT_COMMITTER_EMAIL,
    ENV_GIT_COMMITTER_NAME,
)

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

    try:
        # Stage the codex auth file INSIDE the try so the finally-block cleanup
        # always runs even if this injection raises. The docker copy path IGNORES
        # base_path (it always writes under the /workspace mount), so we cannot
        # inject straight to ~/.codex; we stage it under .setup/ and the setup
        # script (SetupPhaseSecrets._append_codex_auth) relocates it to
        # ~/.codex/auth.json (0600) and removes the staged copy. The secret
        # contents never appear in the setup script text (only the file carries them).
        if secrets.codex_auth_json:
            await ws.inject_files(
                [(".setup/codex-auth.json", secrets.codex_auth_json.encode())],
                base_path="/workspace",
            )

        # Run setup script WITH secrets
        logger.info("Running setup phase with secrets (workspace=%s)", ws.workspace_id)
        from syn_shared.settings import get_settings

        result = await ws.execute(
            ["bash", "/workspace/.setup/setup.sh"],
            environment=setup_env,
            timeout_seconds=get_settings().setup_phase_timeout_seconds,
        )

        if result.exit_code != 0:
            logger.error(
                "Setup phase failed (exit=%d): %s",
                result.exit_code,
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
                await _assert_codex_credential_removed(ws)
        logger.info(
            "Setup phase complete, transient material cleared (workspace=%s)", ws.workspace_id
        )


_CODEX_STAGED_AUTH = "/workspace/.setup/codex-auth.json"


class _CredentialState(StrEnum):
    """What the probe actually established, kept distinct from how it failed.

    ABSENT and "could not tell" MUST NOT share a channel. They did: the check
    read `exit_code != 0` as "gone", which also swallowed a timeout, a provider
    error, and a missing workspace - every way of failing to look became
    evidence of absence.
    """

    PRESENT = "present"
    ABSENT = "absent"
    UNVERIFIABLE = "unverifiable"


#: Printed by the probe so presence is proven by OUTPUT, not only by a status
#: that several unrelated failures can also produce.
_PRESENT_MARKER = "STAGED_CREDENTIAL_PRESENT"
_ABSENT_MARKER = "STAGED_CREDENTIAL_ABSENT"


async def _staged_credential_state(ws: ManagedWorkspace) -> _CredentialState:
    """Ask whether the staged credential exists, and admit when we cannot tell.

    The probe always exits 0 and reports its answer on stdout, so a nonzero
    status means the PROBE failed rather than that the file is gone.
    """
    probe = await ws.execute(
        [
            "sh",
            "-c",
            f"if [ -e {_CODEX_STAGED_AUTH} ]; then echo {_PRESENT_MARKER}; "
            f"else echo {_ABSENT_MARKER}; fi",
        ],
        timeout_seconds=5,
    )

    if probe.exit_code != 0:
        logger.error(
            "SECURITY: could not determine whether a staged codex credential "
            "remains (workspace=%s, exit=%s): %s",
            ws.workspace_id,
            probe.exit_code,
            probe.stderr,
        )
        return _CredentialState.UNVERIFIABLE

    output = (probe.stdout or "").strip()
    if output.endswith(_ABSENT_MARKER):
        return _CredentialState.ABSENT
    if output.endswith(_PRESENT_MARKER):
        return _CredentialState.PRESENT

    # A zero exit with output we do not recognise is not an answer.
    logger.error(
        "SECURITY: unrecognised staged-credential probe output (workspace=%s): %r",
        ws.workspace_id,
        output,
    )
    return _CredentialState.UNVERIFIABLE


async def _assert_codex_credential_removed(ws: ManagedWorkspace) -> None:
    """Guarantee no staged codex credential lingers under /workspace, or raise.

    ``clear_secrets`` removes /workspace/.setup, but if that cleanup failed the
    staged ``codex-auth.json`` could remain readable by the agent. Check,
    force-remove, and RE-VERIFY. If the credential still exists we FAIL CLOSED
    (raise) so a lingering secret is never silently reported as "cleared".
    """
    if await _staged_credential_state(ws) is _CredentialState.ABSENT:
        return

    logger.error(
        "SECURITY: staged codex credential still present under /workspace after "
        "cleanup (workspace=%s); force-removing",
        ws.workspace_id,
    )
    await ws.execute(["rm", "-f", _CODEX_STAGED_AUTH], timeout_seconds=5)

    if await _staged_credential_state(ws) is not _CredentialState.ABSENT:
        # Not `is PRESENT`: an UNVERIFIABLE recheck raises too. A probe that
        # timed out has not shown the credential is gone, and treating that as
        # success is the same fail-open this function exists to prevent.
        msg = (
            f"SECURITY: unable to confirm removal of staged codex credential "
            f"{_CODEX_STAGED_AUTH} (workspace={ws.workspace_id})"
        )
        raise RuntimeError(msg)


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
        timeout_seconds=10,
    )
    if cleanup.exit_code != 0:
        logger.warning(
            "Secret cleanup script exited non-zero (exit=%d, workspace=%s): %s",
            cleanup.exit_code,
            ws.workspace_id,
            cleanup.stderr,
        )

    # Clean up the cleanup script too
    await ws.execute(
        ["rm", "-rf", "/workspace/.cleanup"],
        timeout_seconds=5,
    )
