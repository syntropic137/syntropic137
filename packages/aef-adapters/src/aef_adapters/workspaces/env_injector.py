"""Environment variable injection for isolated workspaces.

This module handles injecting required environment variables into containers,
including API keys for LLM access and other configuration.

See ADR-021: Isolated Workspace Architecture.

Usage:
    from aef_adapters.workspaces.env_injector import EnvInjector

    injector = EnvInjector()
    await injector.inject_api_keys(workspace, executor)
"""

from __future__ import annotations

import logging
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aef_adapters.workspaces.types import IsolatedWorkspace

logger = logging.getLogger(__name__)


@dataclass
class InjectedEnvVar:
    """An environment variable to inject into the container.

    Attributes:
        name: Environment variable name
        value: Value to set (should be obtained from settings)
        required: If True, workspace creation fails if not set
        description: Human-readable description for logging
    """

    name: str
    value: str | None
    required: bool = False
    description: str = ""


class EnvInjector:
    """Injects environment variables into workspaces.

    Handles setting up required environment variables so agents can:
    - Access Claude/Anthropic API
    - Access OpenAI API
    - Use other configured services

    Example:
        injector = EnvInjector()
        await injector.inject_api_keys(workspace, executor)
    """

    def __init__(self) -> None:
        """Initialize the environment injector."""
        pass

    def get_required_env_vars(self) -> list[InjectedEnvVar]:
        """Get list of environment variables to inject.

        Returns:
            List of InjectedEnvVar to inject into workspaces.
        """
        from aef_shared.settings import get_settings

        settings = get_settings()

        env_vars = []

        # Anthropic API Key (for Claude)
        anthropic_key = (
            settings.anthropic_api_key.get_secret_value()
            if settings.anthropic_api_key
            else os.getenv("ANTHROPIC_API_KEY")
        )
        if anthropic_key:
            env_vars.append(
                InjectedEnvVar(
                    name="ANTHROPIC_API_KEY",
                    value=anthropic_key,
                    required=False,  # Not required for all workspaces
                    description="Anthropic API key for Claude",
                )
            )

        # OpenAI API Key (for GPT models)
        openai_key = (
            settings.openai_api_key.get_secret_value()
            if settings.openai_api_key
            else os.getenv("OPENAI_API_KEY")
        )
        if openai_key:
            env_vars.append(
                InjectedEnvVar(
                    name="OPENAI_API_KEY",
                    value=openai_key,
                    required=False,
                    description="OpenAI API key for GPT models",
                )
            )

        return env_vars

    async def inject_api_keys(
        self,
        workspace: IsolatedWorkspace,
        executor: Callable[[IsolatedWorkspace, list[str]], Awaitable[tuple[int, str, str]]],
        *,
        require_anthropic: bool = False,
    ) -> bool:
        """Inject API keys into a workspace.

        Sets environment variables in the container's profile so they
        persist across command executions.

        Args:
            workspace: The isolated workspace
            executor: Async function to execute commands:
                      (workspace, command) -> (exit_code, stdout, stderr)
            require_anthropic: If True, fail if ANTHROPIC_API_KEY not set

        Returns:
            True if all required keys were injected successfully

        Raises:
            ValueError: If required API key is missing
        """
        env_vars = self.get_required_env_vars()

        if not env_vars:
            logger.warning("No API keys configured for injection")
            if require_anthropic:
                msg = (
                    "ANTHROPIC_API_KEY is required but not set. "
                    "Configure via settings.anthropic_api_key or ANTHROPIC_API_KEY env var."
                )
                raise ValueError(msg)
            return True

        # Check for required Anthropic key
        if require_anthropic:
            has_anthropic = any(v.name == "ANTHROPIC_API_KEY" for v in env_vars)
            if not has_anthropic:
                msg = (
                    "ANTHROPIC_API_KEY is required but not set. "
                    "Configure via settings.anthropic_api_key or ANTHROPIC_API_KEY env var."
                )
                raise ValueError(msg)

        # Build script to set environment variables in .bashrc/.profile
        # This ensures they persist across command executions
        export_lines = []
        for env_var in env_vars:
            if env_var.value:
                # Use single quotes to avoid shell expansion issues
                export_lines.append(f"export {env_var.name}='{env_var.value}'")
                logger.debug(f"Injecting {env_var.name} ({env_var.description})")

        if not export_lines:
            return True

        # Write to both .bashrc and .profile for compatibility
        script = "\n".join(export_lines)
        write_cmd = [
            "sh",
            "-c",
            f'echo "{script}" >> ~/.bashrc && echo "{script}" >> ~/.profile',
        ]

        exit_code, _stdout, stderr = await executor(workspace, write_cmd)
        if exit_code != 0:
            logger.error(f"Failed to inject environment variables: {stderr}")
            return False

        # Also export in current session (for immediate use)
        for env_var in env_vars:
            if env_var.value:
                export_cmd = ["sh", "-c", f"export {env_var.name}='{env_var.value}'"]
                await executor(workspace, export_cmd)

        logger.info(f"Injected {len(env_vars)} environment variable(s)")
        return True

    def get_docker_env_args(self) -> list[str]:
        """Get Docker --env arguments for environment variables.

        This is used by Docker backends to inject env vars at container
        creation time (more reliable than writing to .bashrc).

        Returns:
            List of ['--env', 'NAME=value', '--env', 'NAME2=value2', ...]
        """
        env_vars = self.get_required_env_vars()
        args = []

        for env_var in env_vars:
            if env_var.value:
                args.extend(["--env", f"{env_var.name}={env_var.value}"])

        return args


# Singleton instance
_env_injector: EnvInjector | None = None


def get_env_injector() -> EnvInjector:
    """Get the default environment injector instance."""
    global _env_injector
    if _env_injector is None:
        _env_injector = EnvInjector()
    return _env_injector
