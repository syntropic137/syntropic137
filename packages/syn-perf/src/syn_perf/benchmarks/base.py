"""Base benchmark class.

Note: This module is a stub. The workspace isolation benchmarks
need to be updated to work with the new WorkspaceService (ADR-029).
"""

from __future__ import annotations

import asyncio
import time
import uuid
from abc import ABC, abstractmethod
from typing import Any

from syn_perf.metrics import BenchmarkResult, WorkspaceTiming


class BaseBenchmark(ABC):
    """Base class for workspace benchmarks.

    Note: Currently a stub - workspace router not yet integrated.
    """

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

    def log(self, msg: str) -> None:
        """Log message if verbose."""
        if self.verbose:
            print(f"  [DEBUG] {msg}")

    def get_backend_enum(self) -> str:
        """Get backend identifier."""
        return self.backend

    def create_config(self, session_id: str | None = None) -> dict[str, Any]:
        """Create workspace config for benchmark."""
        session_id = session_id or f"perf-{uuid.uuid4().hex[:8]}"

        return {
            "session_id": session_id,
            "cleanup_on_exit": True,
            "isolation_backend": self.backend,
        }

    async def time_workspace_cycle(self, workspace_id: str) -> WorkspaceTiming:
        """Time a complete workspace create/destroy cycle.

        TODO: Integrate with WorkspaceService (ADR-029).

        Args:
            workspace_id: Unique ID for this workspace

        Returns:
            WorkspaceTiming with measured durations
        """
        # Stub implementation - workspace router not yet available
        create_start = time.perf_counter()
        await asyncio.sleep(0.1)  # Simulate workspace creation
        create_end = time.perf_counter()

        destroy_start = time.perf_counter()
        await asyncio.sleep(0.05)  # Simulate workspace destruction
        destroy_end = time.perf_counter()

        create_time_ms = (create_end - create_start) * 1000
        destroy_time_ms = (destroy_end - destroy_start) * 1000
        total_time_ms = (destroy_end - create_start) * 1000

        return WorkspaceTiming(
            workspace_id=workspace_id,
            backend=self.backend,
            create_time_ms=create_time_ms,
            destroy_time_ms=destroy_time_ms,
            total_time_ms=total_time_ms,
            success=True,
            error=None,
        )

    @abstractmethod
    async def run(self, **kwargs: Any) -> BenchmarkResult:  # noqa: ANN401
        """Run the benchmark.

        Returns:
            BenchmarkResult with timing data
        """
        ...
