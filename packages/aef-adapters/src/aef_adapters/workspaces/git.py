"""Git identity and credential injection for isolated workspaces.

This module handles setting up git configuration inside isolated workspaces
so agents can clone repos and commit code with proper attribution.

See ADR-021: Isolated Workspace Architecture - Git Identity section.
See ADR-022: Secure Token Architecture - Token Vending section.

Usage:
    from aef_adapters.workspaces.git import GitInjector

    injector = GitInjector()
    await injector.inject_identity(workspace, git_settings)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from aef_shared.settings.workspace import (
    GitCredentialType,
    GitIdentityResolver,
    GitIdentitySettings,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from aef_adapters.workspaces.types import IsolatedWorkspace


class TokenVendingProtocol(Protocol):
    """Protocol for token vending service (avoid circular imports)."""

    async def vend_github_token(
        self,
        execution_id: str,
        ttl_seconds: int | None = None,
    ) -> str:
        """Vend a short-lived GitHub token for the execution."""
        ...


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
        *,
        execution_id: str | None = None,
        token_vending_service: TokenVendingProtocol | None = None,
    ) -> bool:
        """Inject git identity into a workspace.

        Sets up git user.name and user.email for commits.
        When TokenVendingService is provided, uses short-lived tracked tokens.

        Args:
            workspace: The isolated workspace
            executor: Async function to execute commands:
                      (workspace, command) -> (exit_code, stdout, stderr)
            workflow_override: Optional workflow-specific git settings
            execution_id: Optional execution ID for token tracking
            token_vending_service: Optional token vending service for short-lived tokens

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
            return await self._inject_credentials(
                workspace,
                executor,
                git_settings,
                execution_id=execution_id,
                token_vending_service=token_vending_service,
            )

        return True

    async def _inject_credentials(
        self,
        workspace: IsolatedWorkspace,
        executor: Callable[[IsolatedWorkspace, list[str]], Awaitable[tuple[int, str, str]]],
        git_settings: GitIdentitySettings,
        *,
        execution_id: str | None = None,
        token_vending_service: TokenVendingProtocol | None = None,
    ) -> bool:
        """Inject git credentials for push access.

        Supports:
        - HTTPS with Personal Access Token
        - GitHub App (generates installation token via TokenVendingService)

        Args:
            workspace: The isolated workspace
            executor: Command executor function
            git_settings: Git settings with credentials
            execution_id: Optional execution ID for token tracking
            token_vending_service: Optional token vending service for short-lived tokens

        Returns:
            True if credentials were injected successfully
        """
        if git_settings.credential_type == GitCredentialType.HTTPS:
            return await self._inject_https_credentials(workspace, executor, git_settings)
        elif git_settings.credential_type == GitCredentialType.GITHUB_APP:
            return await self._inject_github_app_credentials(
                workspace,
                executor,
                git_settings,
                execution_id=execution_id,
                token_vending_service=token_vending_service,
            )
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
        *,
        execution_id: str | None = None,
        token_vending_service: TokenVendingProtocol | None = None,
    ) -> bool:
        """Inject GitHub App credentials.

        Uses TokenVendingService when available for short-lived, tracked tokens (5 min).
        Falls back to raw installation token (1 hour) if no token service provided.

        Flow (with TokenVendingService):
        1. Get GitHubAppClient singleton
        2. Vend short-lived token via TokenVendingService (5 min TTL, tracked)
        3. Configure git credential helper with token
        4. Token tracked by execution_id for revocation

        Flow (fallback):
        1. Get GitHubAppClient singleton
        2. Generate installation token directly (1 hour TTL)
        3. Configure git credential helper with token

        Args:
            workspace: The isolated workspace
            executor: Command executor function
            _git_settings: Git settings (GitHub App config comes from settings.github)
            execution_id: Optional execution ID for token tracking
            token_vending_service: Optional token vending service for short-lived tokens

        Returns:
            True if credentials were injected successfully
        """
        try:
            from aef_adapters.github import GitHubAppError, get_github_client

            client = get_github_client()
            token_ttl = "1 hour"

            # Use TokenVendingService if available (preferred - short TTL, tracked)
            if token_vending_service and execution_id:
                try:
                    token = await token_vending_service.vend_github_token(
                        execution_id=execution_id,
                        ttl_seconds=300,  # 5 minutes
                    )
                    token_ttl = "5 minutes (vended)"
                    logger.info(
                        "Using vended GitHub token: execution=%s, ttl=5min",
                        execution_id,
                    )
                except Exception as e:
                    logger.warning(f"TokenVendingService failed, falling back to direct token: {e}")
                    token = await client.get_installation_token()
            else:
                # Fallback: get raw installation token (1 hour TTL)
                token = await client.get_installation_token()
                if execution_id:
                    logger.debug("No TokenVendingService provided, using direct installation token")

            # Configure git to use the token
            # Format: https://x-access-token:TOKEN@github.com
            credentials = f"https://x-access-token:{token}@github.com"

            # Write credentials file with proper permissions
            write_cmd = [
                "sh",
                "-c",
                f'echo "{credentials}" > ~/.git-credentials && chmod 600 ~/.git-credentials',
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

            # Also set GH_TOKEN for gh CLI
            gh_token_cmd = [
                "sh",
                "-c",
                f"echo 'export GH_TOKEN=\"{token}\"' >> ~/.bashrc && "
                f"echo 'export GITHUB_TOKEN=\"{token}\"' >> ~/.bashrc",
            ]
            await executor(workspace, gh_token_cmd)

            logger.info(
                "GitHub App credentials injected: bot=%s, ttl=%s, execution=%s",
                client.bot_username,
                token_ttl,
                execution_id,
            )
            return True

        except GitHubAppError as e:
            logger.error(f"GitHub App authentication failed: {e}")
            return False
        except ValueError as e:
            # GitHub App not configured
            logger.warning(f"GitHub App not configured, skipping: {e}")
            return True


# Singleton instance
_git_injector: GitInjector | None = None


def get_git_injector() -> GitInjector:
    """Get the default git injector instance."""
    global _git_injector
    if _git_injector is None:
        _git_injector = GitInjector()
    return _git_injector
