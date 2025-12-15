"""Agent Container Contract validation.

Validates that a container meets the requirements for agent execution.
This enforces ADR-023: Workspace-First Execution Model.

The contract validates:
- Required commands are available (python, git, gh)
- Required Python modules are installed (aef_agent_runner, anthropic, claude_agent_sdk)

Usage:
    from aef_adapters.workspaces.contract import AgentContainerContract

    # In router.py after creating workspace:
    result = await AgentContainerContract.validate(workspace, executor)
    if not result.passed:
        raise RuntimeError(result.error_message)
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, ClassVar

if TYPE_CHECKING:
    from aef_adapters.workspaces.types import IsolatedWorkspace

logger = logging.getLogger(__name__)


@dataclass
class ContractResult:
    """Result of contract validation."""

    passed: bool
    failures: list[str] = field(default_factory=list)
    fix_instructions: str = ""

    @property
    def error_message(self) -> str:
        """Generate a formatted error message."""
        if self.passed:
            return ""
        msg = "Container contract validation failed:\n"
        for failure in self.failures:
            msg += f"  - {failure}\n"
        if self.fix_instructions:
            msg += f"\nFix: {self.fix_instructions}"
        return msg


# Type for the executor function
CommandExecutor = Callable[
    ["IsolatedWorkspace", list[str]],
    Awaitable[tuple[int, str, str]],
]


class AgentContainerContract:
    """Validates container meets agent execution requirements.

    Enforces ADR-023: Workspace-First Execution Model.

    This contract ensures that before an agent runs inside a container,
    all required tools and packages are available. This prevents silent
    failures where the container starts but can't execute the agent.

    Example:
        async with router.create(config) as workspace:
            result = await AgentContainerContract.validate(
                workspace,
                GVisorWorkspace.execute_command,
            )
            if not result.passed:
                raise RuntimeError(result.error_message)
    """

    # Commands that must be available in the container
    REQUIRED_COMMANDS: ClassVar[list[str]] = ["python", "git", "gh"]

    # Python modules that must be importable
    REQUIRED_MODULES: ClassVar[list[str]] = [
        "aef_agent_runner",
        "anthropic",
        "claude_agent_sdk",
    ]

    @classmethod
    async def validate(
        cls,
        workspace: IsolatedWorkspace,
        executor: CommandExecutor,
    ) -> ContractResult:
        """Verify container is suitable for agent execution.

        Args:
            workspace: The workspace to validate
            executor: Function to execute commands in the workspace

        Returns:
            ContractResult with passed=True if all requirements met,
            or passed=False with list of failures.
        """
        failures: list[str] = []

        # Check required commands
        for cmd in cls.REQUIRED_COMMANDS:
            try:
                code, _, _stderr = await executor(workspace, ["which", cmd])
                if code != 0:
                    failures.append(f"Missing command: {cmd}")
            except Exception as e:
                failures.append(f"Error checking command {cmd}: {e}")

        # Check required Python modules
        for mod in cls.REQUIRED_MODULES:
            try:
                code, _, _stderr = await executor(
                    workspace, ["python", "-c", f"import {mod}"]
                )
                if code != 0:
                    failures.append(f"Missing Python module: {mod}")
            except Exception as e:
                failures.append(f"Error checking module {mod}: {e}")

        if failures:
            logger.warning(
                "Container contract validation failed: %s",
                failures,
                extra={"container_id": workspace.container_id},
            )
            return ContractResult(
                passed=False,
                failures=failures,
                fix_instructions=(
                    "Build workspace image: just workspace-build\n"
                    "Or: docker build -t aef-workspace-claude:latest -f docker/workspace/Dockerfile ."
                ),
            )

        logger.info(
            "Container contract validated: %s",
            workspace.container_id,
            extra={
                "required_commands": cls.REQUIRED_COMMANDS,
                "required_modules": cls.REQUIRED_MODULES,
            },
        )
        return ContractResult(passed=True, failures=[])

    @classmethod
    async def validate_image(
        cls,
        image_name: str,
    ) -> ContractResult:
        """Validate a Docker image without creating a workspace.

        This is useful for pre-flight checks before execution.

        Args:
            image_name: Name of the Docker image to check

        Returns:
            ContractResult with validation status
        """
        import asyncio

        failures: list[str] = []

        # Check required commands
        for cmd in cls.REQUIRED_COMMANDS:
            proc = await asyncio.create_subprocess_exec(
                "docker",
                "run",
                "--rm",
                image_name,
                "which",
                cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.wait()
            if proc.returncode != 0:
                failures.append(f"Missing command: {cmd}")

        # Check required modules
        for mod in cls.REQUIRED_MODULES:
            proc = await asyncio.create_subprocess_exec(
                "docker",
                "run",
                "--rm",
                image_name,
                "python",
                "-c",
                f"import {mod}",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.wait()
            if proc.returncode != 0:
                failures.append(f"Missing Python module: {mod}")

        if failures:
            return ContractResult(
                passed=False,
                failures=failures,
                fix_instructions=(
                    f"Image '{image_name}' is missing required components.\n"
                    "Build workspace image: just workspace-build"
                ),
            )

        return ContractResult(passed=True)
