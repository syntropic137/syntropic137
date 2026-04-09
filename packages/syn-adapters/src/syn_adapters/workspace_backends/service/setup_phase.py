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

    # Run setup script WITH secrets
    logger.info("Running setup phase with secrets (workspace=%s)", ws.workspace_id)
    result = await ws.execute(
        ["bash", "/workspace/.setup/setup.sh"],
        environment=setup_env,
        timeout_seconds=60,  # Setup should be quick
    )

    if result.exit_code != 0:
        logger.error(
            "Setup phase failed (exit=%d): %s",
            result.exit_code,
            result.stderr,
        )
        return result

    # Clear secrets from environment
    await clear_secrets(ws)

    logger.info("Setup phase complete, secrets cleared (workspace=%s)", ws.workspace_id)
    return result


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
    await ws.execute(
        ["bash", "/workspace/.cleanup/clear.sh"],
        timeout_seconds=10,
    )

    # Clean up the cleanup script too
    await ws.execute(
        ["rm", "-rf", "/workspace/.cleanup"],
        timeout_seconds=5,
    )
