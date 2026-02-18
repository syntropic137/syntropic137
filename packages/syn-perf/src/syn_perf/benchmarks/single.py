"""Single workspace benchmark - measures individual create/destroy cycles."""

from __future__ import annotations

import uuid
from typing import Any

from syn_perf.benchmarks.base import BaseBenchmark
from syn_perf.metrics import BenchmarkResult


class SingleBenchmark(BaseBenchmark):
    """Benchmark single workspace create/destroy cycles.

    Measures timing for:
    - Workspace creation (container/VM startup)
    - Workspace destruction (cleanup)
    - Total cycle time

    Usage:
        benchmark = SingleBenchmark(backend="docker_hardened")
        result = await benchmark.run(iterations=10)
        print(f"Mean create time: {result.create_times_ms}")
    """

    benchmark_type = "single"

    async def run(self, iterations: int = 10, **_kwargs: Any) -> BenchmarkResult:
        """Run single workspace benchmark.

        Args:
            iterations: Number of cycles to run

        Returns:
            BenchmarkResult with timing data
        """
        result = BenchmarkResult(
            benchmark_type=self.benchmark_type,
            backend=self.backend,
            iterations=iterations,
        )

        for i in range(iterations):
            workspace_id = f"single-{uuid.uuid4().hex[:8]}"
            self.log(f"Iteration {i + 1}/{iterations}")

            timing = await self.time_workspace_cycle(workspace_id)
            result.add_timing(timing)

        result.complete()
        return result
