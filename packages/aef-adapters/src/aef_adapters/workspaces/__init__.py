"""Workspace adapters - isolated execution environments for agents.

⚠️  DEPRECATED MODULE - MIGRATION IN PROGRESS ⚠️

This module is deprecated and will be removed in a future release.
The new workspace implementation is in `aef_domain.contexts.workspaces/`.

Migration Guide:
    OLD (deprecated):
        from aef_adapters.workspaces import get_workspace_router
        router = get_workspace_router()
        async with router.create(config) as workspace:
            await router.execute_command(workspace, ["cmd"])

    NEW (use this):
        from aef_domain.contexts.workspaces import WorkspaceAggregate
        from aef_adapters.workspace_backends.docker import DockerIsolationAdapter
        # See aef_domain.contexts.workspaces.README.md for full migration guide

Problems with this module:
    - Fat orchestrator in router.py (789 lines) - untestable
    - Mixed concerns: git, env, logging, contracts in one place
    - Sidecar not integrated (ADR-022 violation)
    - Token vending disconnected from sidecar
    - No domain model - just dataclasses
    - Events not event-sourced - no audit trail

New architecture:
    - Event-sourced WorkspaceAggregate in domain layer
    - Clean port interfaces for DI (IsolationBackendPort, SidecarPort, etc.)
    - Adapters per backend (docker/, firecracker/, cloud/, memory/)
    - Proper token injection via sidecar per ADR-022

See: PROJECT-PLAN_20251215_WORKSPACE-BOUNDED-CONTEXT.md

---
LEGACY DOCUMENTATION (for reference during migration):

This module provides workspace implementations for agentic execution.

IMPORTANT (ADR-023): LocalWorkspace is TEST ONLY and will FAIL in other environments.
Use WorkspaceRouter for development and production.

Test-Only Workspaces:
- LocalWorkspace: File-based workspace in temp directories (TEST ONLY)
- InMemoryWorkspace: Pure in-memory workspace for fast tests (TEST ONLY)

Isolated Backends (development and production):
- GVisorWorkspace: Docker + gVisor runtime
- HardenedDockerWorkspace: Docker with security hardening
- FirecrackerWorkspace: Firecracker MicroVMs
- E2BWorkspace: E2B cloud sandboxes

Quick Start (Development/Production - use WorkspaceRouter):
    from aef_adapters.workspaces import get_workspace_router

    router = get_workspace_router()
    async with router.create(config) as workspace:
        # Workspace is isolated (Docker, gVisor, etc.)
        await router.execute_command(workspace, ["python", "script.py"])
        artifacts = await router.collect_artifacts(workspace)

Quick Start (Tests only):
    from aef_adapters.workspaces import InMemoryWorkspace

    # Only works when APP_ENVIRONMENT=test
    async with InMemoryWorkspace.create(config) as workspace:
        await workspace.write_file("test.txt", b"hello")

See ADR-023: Workspace-First Execution Model (enforcement)
See ADR-021: Isolated Workspace Architecture (backends)
"""

import warnings

warnings.warn(
    "aef_adapters.workspaces is deprecated. "
    "Use aef_domain.contexts.workspaces with aef_adapters.workspace_backends instead. "
    "See PROJECT-PLAN_20251215_WORKSPACE-BOUNDED-CONTEXT.md for migration guide.",
    DeprecationWarning,
    stacklevel=2,
)

from aef_adapters.workspaces.base import BaseIsolatedWorkspace
from aef_adapters.workspaces.collector_emitter import (
    CollectorEmitter,
    InMemoryCollectorEmitter,
)
from aef_adapters.workspaces.docker_hardened import HardenedDockerWorkspace
from aef_adapters.workspaces.e2b import E2BWorkspace
from aef_adapters.workspaces.env_injector import (
    EnvInjector,
    InjectedEnvVar,
    get_env_injector,
)
from aef_adapters.workspaces.events import (
    WorkspaceEventEmitter,
    configure_workspace_emitter,
    get_workspace_emitter,
)
from aef_adapters.workspaces.firecracker import FirecrackerWorkspace
from aef_adapters.workspaces.git import (
    ExecutionContext,
    GitInjector,
    build_commit_message,
    get_git_injector,
)
from aef_adapters.workspaces.gvisor import GVisorWorkspace
from aef_adapters.workspaces.local import LocalWorkspace, NonIsolatedWorkspaceError
from aef_adapters.workspaces.logging import (
    ContainerLogStreamer,
    LogEntry,
    LogLevel,
    StructuredLogger,
    ViewContainerLogsTool,
    create_container_logger,
)
from aef_adapters.workspaces.memory import (
    InMemoryWorkspace,
    TestEnvironmentRequiredError,
)
from aef_adapters.workspaces.network import (
    DEFAULT_ALLOWED_HOSTS,
    EgressProxy,
    NetworkConfig,
    ensure_proxy_running,
    get_egress_proxy,
    inject_proxy_config,
)
from aef_adapters.workspaces.protocol import IsolatedWorkspaceProtocol, WorkspaceProtocol
from aef_adapters.workspaces.router import (
    RouterStats,
    WorkspaceRouter,
    get_workspace_router,
    reset_workspace_router,
)
from aef_adapters.workspaces.types import IsolatedWorkspace, IsolatedWorkspaceConfig

__all__ = [
    "DEFAULT_ALLOWED_HOSTS",
    "BaseIsolatedWorkspace",
    "CollectorEmitter",
    "ContainerLogStreamer",
    "E2BWorkspace",
    "EgressProxy",
    "EnvInjector",
    "ExecutionContext",
    "FirecrackerWorkspace",
    "GVisorWorkspace",
    "GitInjector",
    "HardenedDockerWorkspace",
    "InMemoryCollectorEmitter",
    "InMemoryWorkspace",
    "InjectedEnvVar",
    "IsolatedWorkspace",
    "IsolatedWorkspaceConfig",
    "IsolatedWorkspaceProtocol",
    "LocalWorkspace",
    "LogEntry",
    "LogLevel",
    "NetworkConfig",
    "NonIsolatedWorkspaceError",
    "RouterStats",
    "StructuredLogger",
    "TestEnvironmentRequiredError",
    "ViewContainerLogsTool",
    "WorkspaceEventEmitter",
    "WorkspaceProtocol",
    "WorkspaceRouter",
    "build_commit_message",
    "configure_workspace_emitter",
    "create_container_logger",
    "ensure_proxy_running",
    "get_egress_proxy",
    "get_env_injector",
    "get_git_injector",
    "get_workspace_emitter",
    "get_workspace_router",
    "inject_proxy_config",
    "reset_workspace_router",
]
