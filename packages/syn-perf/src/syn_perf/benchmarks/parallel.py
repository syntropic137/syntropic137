"""Parallel workspace benchmark - measures concurrent scaling."""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any

from syn_perf.benchmarks.base import BaseBenchmark
from syn_perf.metrics import BenchmarkResult, WorkspaceTiming


class ParallelBenchmark(BaseBenchmark):
    """Benchmark parallel workspace creation.

    Measures:
    - Total time to create N workspaces concurrently
    - Individual workspace timings
    - Speedup vs sequential execution

    Usage:
        benchmark = ParallelBenchmark(backend="docker_hardened")
        result = await benchmark.run(count=10)
        print(f"Parallel speedup: {result.metadata['speedup']}x")
    """

    benchmark_type = "parallel"

    async def run(self, count: int = 10, **_kwargs: Any) -> BenchmarkResult:
        """Run parallel workspace benchmark.

        Args:
            count: Number of concurrent workspaces to create

        Returns:
            BenchmarkResult with parallel timing data
        """
        result = BenchmarkResult(
            benchmark_type=self.benchmark_type,
            backend=self.backend,
            iterations=count,
            concurrent_count=count,
        )

        # Generate workspace IDs
        workspace_ids = [f"parallel-{uuid.uuid4().hex[:8]}" for _ in range(count)]

        # Create tasks for parallel execution
        tasks = [self.time_workspace_cycle(wid) for wid in workspace_ids]

        # Run all in parallel and time it
        self.log(f"Starting {count} workspaces in parallel...")
        start_time = time.perf_counter()
        timings = await asyncio.gather(*tasks, return_exceptions=True)
        end_time = time.perf_counter()

        total_parallel_time_ms = (end_time - start_time) * 1000
        result.total_parallel_time_ms = total_parallel_time_ms

        # Process results
        for timing in timings:
            if isinstance(timing, Exception):
                # Handle exceptions from gather
                result.add_timing(
                    WorkspaceTiming(
                        workspace_id="unknown",
                        backend=self.backend,
                        create_time_ms=0,
                        destroy_time_ms=0,
                        total_time_ms=0,
                        success=False,
                        error=str(timing),
                    )
                )
            elif isinstance(timing, WorkspaceTiming):
                result.add_timing(timing)

        # Calculate speedup
        if result.total_times_ms:
            sequential_estimate_ms = sum(result.total_times_ms)
            speedup = (
                sequential_estimate_ms / total_parallel_time_ms if total_parallel_time_ms > 0 else 0
            )
            result.metadata["sequential_estimate_ms"] = sequential_estimate_ms
            result.metadata["speedup"] = round(speedup, 2)
            result.metadata["avg_per_workspace_ms"] = total_parallel_time_ms / count

        result.complete()
        return result
