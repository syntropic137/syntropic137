"""Factory for creating workflow executors, agentic agents, and isolated workspaces.

Provides factory patterns for instantiating:
- WorkflowExecutor (unified, with required observability)
- Agentic agents that implement AgenticProtocol
- Isolated workspaces via WorkspaceRouter

Example:
    from aef_adapters.orchestration import create_workflow_executor

    # Create unified executor (recommended)
    executor = create_workflow_executor(
        agent_factory=get_agentic_agent,
        workspace_service=workspace_service,
    )

    async for event in executor.execute(workflow, inputs):
        process(event)

See:
- ADR-021: Isolated Workspace Architecture
- ADR-027: Unified Workflow Executor Architecture (M8)
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable
    from contextlib import AbstractAsyncContextManager as AsyncContextManager

    from agentic_observability import ObservabilityPort

    from aef_adapters.agents.agentic_protocol import AgenticProtocol
    from aef_adapters.agents.agentic_types import Workspace, WorkspaceConfig
    from aef_adapters.control import ControlSignal
    from aef_adapters.orchestration.workflow_executor import WorkflowExecutor
    from aef_adapters.workspace_backends.service import WorkspaceService

logger = logging.getLogger(__name__)


# =============================================================================
# Workflow Executor Factory (M8: Unified Executor Architecture)
# =============================================================================


def create_workflow_executor(
    agent_factory: Callable[[str], AgenticProtocol] | None = None,
    workspace_service: WorkspaceService | None = None,
    *,
    observability: ObservabilityPort | None = None,
    default_provider: str = "claude",
    default_max_turns: int = 50,
    default_max_budget_usd: float | None = None,
    control_signal_checker: Callable[[str], Awaitable[ControlSignal | None]] | None = None,
) -> WorkflowExecutor:
    """Create a unified WorkflowExecutor with proper DI wiring.

    This is the recommended way to create a WorkflowExecutor. It:
    - Automatically configures TimescaleObservability if not provided
    - Validates all required dependencies
    - Provides sensible defaults

    Args:
        agent_factory: Factory for creating agentic agents.
            Defaults to get_agentic_agent.
        workspace_service: WorkspaceService for isolated workspaces.
            Required - must be provided.
        observability: ObservabilityPort for telemetry.
            Defaults to get_observability() (TimescaleDB).
        default_provider: Default agent provider (e.g., "claude").
        default_max_turns: Default max turns per phase.
        default_max_budget_usd: Optional budget limit per phase.
        control_signal_checker: Optional callback for pause/resume/cancel.

    Returns:
        Configured WorkflowExecutor ready for execution.

    Raises:
        ValueError: If workspace_service is not provided.

    Example:
        from aef_adapters.orchestration import create_workflow_executor
        from aef_adapters.workspace_backends.service import WorkspaceService

        executor = create_workflow_executor(
            workspace_service=WorkspaceService.create_docker(),
        )

        async for event in executor.execute(workflow, inputs):
            print(event)
    """
    from aef_adapters.orchestration.workflow_executor import WorkflowExecutor

    # Validate required dependencies
    if workspace_service is None:
        raise ValueError(
            "workspace_service is required. "
            "Use WorkspaceService.create_docker() for production, "
            "or WorkspaceService.create_memory() for tests."
        )

    # Default agent factory
    if agent_factory is None:
        agent_factory = get_agentic_agent

    # Default observability (TimescaleDB)
    if observability is None:
        from aef_adapters.observability import get_observability

        observability = get_observability()

    return WorkflowExecutor(
        observability=observability,
        agent_factory=agent_factory,
        workspace_service=workspace_service,
        default_provider=default_provider,
        default_max_turns=default_max_turns,
        default_max_budget_usd=default_max_budget_usd,
        control_signal_checker=control_signal_checker,
    )


class AgenticAgentFactory(Protocol):
    """Protocol for agentic agent factory functions."""

    def __call__(self, provider: str) -> AgenticProtocol:
        """Create an agentic agent for the given provider."""
        ...


def get_agentic_agent(provider: str) -> AgenticProtocol:
    """Get an agentic agent for the specified provider.

    Args:
        provider: Provider name (e.g., "claude", "openai").

    Returns:
        An AgenticProtocol implementation for the provider.

    Raises:
        ValueError: If the provider is not supported.
        RuntimeError: If the agent is not available (missing API key, etc.).

    Example:
        agent = get_agentic_agent("claude")
        if agent.is_available:
            async for event in agent.execute(task, workspace, config):
                handle_event(event)
    """

    # Normalize provider name
    provider_lower = provider.lower()

    if provider_lower in ("claude", "anthropic"):
        from aef_adapters.agents.claude_agentic import ClaudeAgenticAgent

        agent = ClaudeAgenticAgent()
        if not agent.is_available:
            logger.warning(
                "ClaudeAgenticAgent is not available. "
                "Check ANTHROPIC_API_KEY and claude-agent-sdk installation."
            )
        return agent

    # TODO: Add more providers (OpenAI, etc.) as they become available

    supported = ["claude", "anthropic"]
    raise ValueError(f"Unsupported agentic provider: {provider}. Supported providers: {supported}")


def get_available_agentic_agents() -> list[str]:
    """Get list of available agentic agent providers.

    Returns:
        List of provider names that have available agents.
    """
    available = []

    # Check Claude
    try:
        from aef_adapters.agents.claude_agentic import ClaudeAgenticAgent

        agent = ClaudeAgenticAgent()
        if agent.is_available:
            available.append("claude")
    except ImportError:
        # ClaudeAgenticAgent requires claude-agent-sdk optional dependency.
        # If it cannot be imported, this provider is not available.
        pass

    return available


# =============================================================================
# Workspace Factory
# =============================================================================


class WorkspaceFactory(Protocol):
    """Protocol for workspace factory functions."""

    def __call__(self, config: WorkspaceConfig) -> AsyncContextManager[Workspace]:
        """Create a workspace for the given configuration."""
        ...


@asynccontextmanager
async def get_workspace(config: WorkspaceConfig) -> AsyncIterator[Workspace]:
    """Get an isolated workspace for agent execution.

    Uses WorkspaceRouter to create properly isolated workspaces.
    In production, this uses Docker/Firecracker/gVisor isolation.
    In development/testing, may fall back to local workspaces if configured.

    Args:
        config: Workspace configuration (session_id, paths, etc.)

    Yields:
        A configured Workspace for agent execution

    Example:
        async with get_workspace(config) as workspace:
            async for event in agent.execute(task, workspace, exec_config):
                handle_event(event)

    See ADR-021: Isolated Workspace Architecture
    """
    from aef_adapters.agents.agentic_types import Workspace
    from aef_adapters.workspaces import (
        IsolatedWorkspaceConfig,
        get_workspace_router,
    )

    # Wrap agent WorkspaceConfig in IsolatedWorkspaceConfig
    # The agent's WorkspaceConfig is compatible with IsolatedWorkspaceConfig.base_config
    isolated_config = IsolatedWorkspaceConfig(
        base_config=config,
        # Use settings defaults for isolation_backend, docker_image, etc.
    )

    # Use the router to create an isolated workspace
    router = get_workspace_router()

    async with router.create(isolated_config) as isolated_workspace:
        # Convert IsolatedWorkspace to agent Workspace type
        # The agent Workspace is a simple dataclass with path and config
        agent_workspace = Workspace(
            path=isolated_workspace.path,
            config=config,
        )

        # Store the router reference for command execution
        agent_workspace._router = router  # type: ignore[attr-defined]
        agent_workspace._isolated_workspace = isolated_workspace  # type: ignore[attr-defined]

        yield agent_workspace


async def execute_in_workspace(
    workspace: Workspace,
    command: list[str],
    timeout: int | None = None,
    cwd: str | None = None,
) -> tuple[int, str, str]:
    """Execute a command in an isolated workspace.

    This helper function executes commands through the WorkspaceRouter,
    ensuring proper isolation.

    Args:
        workspace: Agent workspace (from get_workspace)
        command: Command and arguments
        timeout: Optional timeout in seconds
        cwd: Working directory inside workspace

    Returns:
        Tuple of (exit_code, stdout, stderr)

    Raises:
        RuntimeError: If workspace was not created via get_workspace
    """
    router = getattr(workspace, "_router", None)
    isolated = getattr(workspace, "_isolated_workspace", None)

    if router is None or isolated is None:
        raise RuntimeError(
            "Workspace was not created via get_workspace(). "
            "Cannot execute commands in non-isolated workspace."
        )

    return await router.execute_command(isolated, command, timeout, cwd)


def get_workspace_local(config: WorkspaceConfig) -> AsyncContextManager[Workspace]:
    """Get a LOCAL workspace for testing/development ONLY.

    WARNING: This bypasses isolation! Only use in tests or dev.
    In production, use get_workspace() which provides proper isolation.

    Args:
        config: Workspace configuration

    Returns:
        An async context manager that yields a non-isolated Workspace.

    See ADR-004: Environment Configuration (Mock Objects Policy)
    """
    from aef_adapters.workspaces import LocalWorkspace

    return LocalWorkspace.create(config)
