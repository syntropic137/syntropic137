"""Git identity and credential injection for isolated workspaces.

This module handles setting up git configuration inside isolated workspaces
so agents can clone repos and commit code with proper attribution.

See ADR-021: Isolated Workspace Architecture - Git Identity section.

Usage:
    from aef_adapters.workspaces.git import GitInjector

    injector = GitInjector()
    await injector.inject_identity(workspace, git_settings)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from aef_shared.settings.workspace import (
    GitCredentialType,
    GitIdentityResolver,
    GitIdentitySettings,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from aef_adapters.workspaces.types import IsolatedWorkspace

logger = logging.getLogger(__name__)


@dataclass
class ExecutionContext:
    """Context for agent execution, used in commit messages.

    Attributes:
        workflow_id: Unique identifier for the workflow
        execution_id: Unique identifier for this execution
        session_id: VSA session ID
        initiated_by_name: Name of the user who initiated the workflow
        initiated_by_email: Email of the user who initiated the workflow
    """

    workflow_id: str | None = None
    execution_id: str | None = None
    session_id: str | None = None
    initiated_by_name: str | None = None
    initiated_by_email: str | None = None


def build_commit_message(summary: str, context: ExecutionContext | None = None) -> str:
    """Build a commit message with AEF metadata.

    Creates a commit message that includes information about the agent
    execution for traceability.

    Args:
        summary: The commit summary (first line)
        context: Optional execution context for metadata

    Returns:
        Complete commit message with metadata footer

    Example:
        >>> ctx = ExecutionContext(
        ...     workflow_id="code-review-123",
        ...     execution_id="exec-abc",
        ...     session_id="session-xyz",
        ...     initiated_by_name="John",
        ...     initiated_by_email="john@example.com"
        ... )
        >>> msg = build_commit_message("Fix bug in parser", ctx)
        >>> print(msg)
        Fix bug in parser

        Applied by AEF agent
        - Workflow: code-review-123
        - Execution: exec-abc
        - Session: session-xyz

        Co-authored-by: John <john@example.com>
    """
    lines = [summary, ""]

    if context:
        lines.append("Applied by AEF agent")
        if context.workflow_id:
            lines.append(f"- Workflow: {context.workflow_id}")
        if context.execution_id:
            lines.append(f"- Execution: {context.execution_id}")
        if context.session_id:
            lines.append(f"- Session: {context.session_id}")

        if context.initiated_by_name and context.initiated_by_email:
            lines.append("")
            lines.append(
                f"Co-authored-by: {context.initiated_by_name} <{context.initiated_by_email}>"
            )
    else:
        lines.append("Applied by AEF agent")

    return "\n".join(lines)


class GitInjector:
    """Injects git identity and credentials into workspaces.

    Handles setting up git configuration so agents can:
    - Clone private repositories
    - Commit code with proper author attribution
    - Push changes back to remote

    Example:
        injector = GitInjector()
        await injector.inject_identity(workspace, git_settings, executor)
    """

    def __init__(self) -> None:
        """Initialize the git injector."""
        self._resolver = GitIdentityResolver()

    async def inject_identity(
        self,
        workspace: IsolatedWorkspace,
        executor: Callable[[IsolatedWorkspace, list[str]], Awaitable[tuple[int, str, str]]],
        workflow_override: GitIdentitySettings | None = None,
    ) -> bool:
        """Inject git identity into a workspace.

        Sets up git user.name and user.email for commits.

        Args:
            workspace: The isolated workspace
            executor: Async function to execute commands:
                      (workspace, command) -> (exit_code, stdout, stderr)
            workflow_override: Optional workflow-specific git settings

        Returns:
            True if identity was injected successfully

        Raises:
            ValueError: If git identity cannot be resolved
        """
        try:
            git_settings = self._resolver.resolve(workflow_override)
        except ValueError:
            # No identity configured - log warning but don't fail
            # Some workspaces might not need git
            logger.warning("No git identity configured, skipping injection")
            return False

        if not git_settings.is_configured:
            logger.warning("Git identity incomplete, skipping injection")
            return False

        # Set git user.name (is_configured ensures user_name is not None)
        assert git_settings.user_name is not None
        exit_code, _stdout, stderr = await executor(
            workspace,
            ["git", "config", "--global", "user.name", git_settings.user_name],
        )
        if exit_code != 0:
            logger.error(f"Failed to set git user.name: {stderr}")
            return False

        # Set git user.email (is_configured ensures user_email is not None)
        assert git_settings.user_email is not None
        exit_code, _stdout, stderr = await executor(
            workspace,
            ["git", "config", "--global", "user.email", git_settings.user_email],
        )
        if exit_code != 0:
            logger.error(f"Failed to set git user.email: {stderr}")
            return False

        logger.info(f"Git identity injected: {git_settings.user_name} <{git_settings.user_email}>")

        # Inject credentials if available
        if git_settings.has_credentials:
            return await self._inject_credentials(workspace, executor, git_settings)

        return True

    async def _inject_credentials(
        self,
        workspace: IsolatedWorkspace,
        executor: Callable[[IsolatedWorkspace, list[str]], Awaitable[tuple[int, str, str]]],
        git_settings: GitIdentitySettings,
    ) -> bool:
        """Inject git credentials for push access.

        Supports:
        - HTTPS with Personal Access Token
        - GitHub App (generates installation token)

        Args:
            workspace: The isolated workspace
            executor: Command executor function
            git_settings: Git settings with credentials

        Returns:
            True if credentials were injected successfully
        """
        if git_settings.credential_type == GitCredentialType.HTTPS:
            return await self._inject_https_credentials(workspace, executor, git_settings)
        elif git_settings.credential_type == GitCredentialType.GITHUB_APP:
            return await self._inject_github_app_credentials(workspace, executor, git_settings)
        return True

    async def _inject_https_credentials(
        self,
        workspace: IsolatedWorkspace,
        executor: Callable[[IsolatedWorkspace, list[str]], Awaitable[tuple[int, str, str]]],
        git_settings: GitIdentitySettings,
    ) -> bool:
        """Inject HTTPS credentials using git-credentials store.

        Creates ~/.git-credentials file with the token.

        Args:
            workspace: The isolated workspace
            executor: Command executor function
            git_settings: Git settings with HTTPS token

        Returns:
            True if credentials were injected successfully
        """
        if not git_settings.token:
            return True

        token = git_settings.token.get_secret_value()

        # Create credentials file content
        # Format: https://TOKEN:x-oauth-basic@github.com
        credentials = f"https://{token}:x-oauth-basic@github.com"

        # Write credentials file with proper permissions
        # Using shell to handle file creation safely
        write_cmd = [
            "sh",
            "-c",
            f'mkdir -p ~/.git-credentials.d && echo "{credentials}" > ~/.git-credentials && chmod 600 ~/.git-credentials',
        ]

        exit_code, _stdout, stderr = await executor(workspace, write_cmd)
        if exit_code != 0:
            logger.error(f"Failed to write git credentials: {stderr}")
            return False

        # Configure git to use the credential store
        exit_code, _stdout, stderr = await executor(
            workspace,
            ["git", "config", "--global", "credential.helper", "store"],
        )
        if exit_code != 0:
            logger.error(f"Failed to configure credential helper: {stderr}")
            return False

        logger.info("Git HTTPS credentials injected")
        return True

    async def _inject_github_app_credentials(
        self,
        workspace: IsolatedWorkspace,
        executor: Callable[[IsolatedWorkspace, list[str]], Awaitable[tuple[int, str, str]]],
        _git_settings: GitIdentitySettings,
    ) -> bool:
        """Inject GitHub App credentials.

        This generates a short-lived installation token from the App credentials
        and uses it for git operations.

        Args:
            workspace: The isolated workspace
            executor: Command executor function
            git_settings: Git settings with GitHub App credentials

        Returns:
            True if credentials were injected successfully
        """
        try:
            credentials = await get_github_credentials()
            if credentials is None:
                logger.warning(
                    "GitHub App not configured or token generation failed. "
                    "Falling back to no credentials."
                )
                return True

            token, user_name, user_email = credentials

            # Override git identity with bot identity
            exit_code, _stdout, stderr = await executor(
                workspace,
                ["git", "config", "--global", "user.name", user_name],
            )
            if exit_code != 0:
                logger.error(f"Failed to set GitHub App bot name: {stderr}")
                return False

            exit_code, _stdout, stderr = await executor(
                workspace,
                ["git", "config", "--global", "user.email", user_email],
            )
            if exit_code != 0:
                logger.error(f"Failed to set GitHub App bot email: {stderr}")
                return False

            # Create credentials file with the installation token
            # Format: https://x-access-token:TOKEN@github.com
            # Use base64 encoding to avoid shell injection risks
            import base64

            cred_line = f"https://x-access-token:{token}@github.com"
            cred_b64 = base64.b64encode(cred_line.encode()).decode()

            # Write credentials file with proper permissions using base64 decode
            # This avoids shell injection since base64 is safe for shell interpolation
            write_cmd = [
                "sh",
                "-c",
                f"echo '{cred_b64}' | base64 -d > ~/.git-credentials && chmod 600 ~/.git-credentials",
            ]

            exit_code, _stdout, stderr = await executor(workspace, write_cmd)
            if exit_code != 0:
                logger.error(f"Failed to write GitHub App credentials: {stderr}")
                return False

            # Configure git to use the credential store
            exit_code, _stdout, stderr = await executor(
                workspace,
                ["git", "config", "--global", "credential.helper", "store"],
            )
            if exit_code != 0:
                logger.error(f"Failed to configure credential helper: {stderr}")
                return False

            logger.info(f"GitHub App credentials injected: {user_name}")
            return True

        except Exception:
            logger.exception("Failed to inject GitHub App credentials")
            return False


# Singleton instance
_git_injector: GitInjector | None = None


def get_git_injector() -> GitInjector:
    """Get the default git injector instance."""
    global _git_injector
    if _git_injector is None:
        _git_injector = GitInjector()
    return _git_injector


async def get_github_credentials() -> tuple[str, str, str] | None:
    """Get GitHub App credentials for workspace injection.

    Fetches an installation token from the configured GitHub App
    and returns it along with the bot identity.

    Returns:
        Tuple of (token, user_name, user_email) if GitHub App is configured,
        None otherwise.

    Usage:
        credentials = await get_github_credentials()
        if credentials:
            token, user_name, user_email = credentials
            # Use token for git operations
    """
    try:
        from aef_shared.settings.github import get_github_settings
    except ImportError:
        logger.debug("GitHub settings not available")
        return None

    settings = get_github_settings()

    if not settings.is_configured:
        logger.debug("GitHub App not configured")
        return None

    try:
        from aef_domain.contexts.github._shared.github_client import (
            GitHubAppClient,
        )

        client = GitHubAppClient(settings)
        token_response = await client.get_installation_token()

        return (
            token_response.token,
            settings.bot_name,
            settings.bot_email,
        )
    except Exception:
        logger.exception("Failed to get GitHub App token")
        return None
