"""Base benchmark class."""

from __future__ import annotations

import asyncio
import time
import uuid
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

from aef_perf.metrics import BenchmarkResult, WorkspaceTiming

if TYPE_CHECKING:
    from aef_adapters.workspaces import IsolatedWorkspaceConfig, WorkspaceRouter
    from aef_shared.settings import IsolationBackend


class BaseBenchmark(ABC):
    """Base class for workspace benchmarks."""

    benchmark_type: str = "base"

    def __init__(
        self,
        backend: str = "docker_hardened",
        verbose: bool = False,
    ) -> None:
        """Initialize benchmark.

        Args:
            backend: Isolation backend to test
            verbose: Enable verbose output
        """
        self.backend = backend
        self.verbose = verbose
        self._router: WorkspaceRouter | None = None

    def log(self, msg: str) -> None:
        """Log message if verbose."""
        if self.verbose:
            print(f"  [DEBUG] {msg}")

    def get_router(self) -> WorkspaceRouter:
        """Get or create workspace router."""
        if self._router is None:
            from aef_adapters.workspaces import WorkspaceRouter

            self._router = WorkspaceRouter()
        return self._router

    def get_backend_enum(self) -> IsolationBackend:
        """Convert backend string to enum."""
        from aef_shared.settings import IsolationBackend

        return IsolationBackend(self.backend)

    def create_config(self, session_id: str | None = None) -> IsolatedWorkspaceConfig:
        """Create workspace config for benchmark."""
        from aef_adapters.agents.agentic_types import WorkspaceConfig
        from aef_adapters.workspaces import IsolatedWorkspaceConfig

        session_id = session_id or f"perf-{uuid.uuid4().hex[:8]}"

        base_config = WorkspaceConfig(
            session_id=session_id,
            cleanup_on_exit=True,
        )

        return IsolatedWorkspaceConfig(
            base_config=base_config,
            isolation_backend=self.get_backend_enum(),
        )

    async def time_workspace_cycle(self, workspace_id: str) -> WorkspaceTiming:
        """Time a complete workspace create/destroy cycle.

        Args:
            workspace_id: Unique ID for this workspace

        Returns:
            WorkspaceTiming with measured durations
        """
        router = self.get_router()
        config = self.create_config(workspace_id)
        backend_enum = self.get_backend_enum()

        create_start = time.perf_counter()
        create_end = 0.0
        destroy_start = 0.0
        destroy_end = 0.0
        error: str | None = None
        success = True

        try:
            self.log(f"Creating workspace {workspace_id}...")
            async with router.create(config, backend=backend_enum) as _workspace:
                create_end = time.perf_counter()
                self.log(
                    f"Workspace {workspace_id} created in {(create_end - create_start) * 1000:.0f}ms"
                )

                # Small delay to simulate minimal work
                await asyncio.sleep(0.01)

                destroy_start = time.perf_counter()
            # Context exit triggers destroy
            destroy_end = time.perf_counter()
            self.log(
                f"Workspace {workspace_id} destroyed in {(destroy_end - destroy_start) * 1000:.0f}ms"
            )

        except Exception as e:
            success = False
            error = str(e)
            destroy_end = time.perf_counter()
            self.log(f"Workspace {workspace_id} failed: {error}")

        create_time_ms = (create_end - create_start) * 1000 if create_end else 0
        destroy_time_ms = (destroy_end - destroy_start) * 1000 if destroy_start else 0
        total_time_ms = (destroy_end - create_start) * 1000

        return WorkspaceTiming(
            workspace_id=workspace_id,
            backend=self.backend,
            create_time_ms=create_time_ms,
            destroy_time_ms=destroy_time_ms,
            total_time_ms=total_time_ms,
            success=success,
            error=error,
        )

    @abstractmethod
    async def run(self, **kwargs: Any) -> BenchmarkResult:
        """Run the benchmark.

        Returns:
            BenchmarkResult with timing data
        """
        ...
