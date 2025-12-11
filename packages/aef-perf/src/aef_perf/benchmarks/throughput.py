"""Throughput benchmark - measures workspaces per second."""

from __future__ import annotations

import asyncio
import time
import uuid

from aef_perf.benchmarks.base import BaseBenchmark
from aef_perf.metrics import BenchmarkResult


class ThroughputBenchmark(BaseBenchmark):
    """Benchmark workspace throughput.

    Creates and destroys workspaces as fast as possible
    for a specified duration, measuring workspaces/second.

    Usage:
        benchmark = ThroughputBenchmark(backend="docker_hardened")
        result = await benchmark.run(duration=60)
        print(f"Throughput: {result.workspaces_per_second} workspaces/sec")
    """

    benchmark_type = "throughput"

    async def run(
        self,
        duration: float = 30.0,
        max_concurrent: int = 5,
    ) -> BenchmarkResult:
        """Run throughput benchmark.

        Args:
            duration: How long to run in seconds
            max_concurrent: Maximum concurrent workspaces

        Returns:
            BenchmarkResult with throughput data
        """
        result = BenchmarkResult(
            benchmark_type=self.benchmark_type,
            backend=self.backend,
            iterations=0,  # Will be updated
            duration_seconds=duration,
        )

        start_time = time.perf_counter()
        end_time = start_time + duration
        active_tasks: set[asyncio.Task] = set()
        completed_count = 0

        self.log(f"Running throughput test for {duration}s with {max_concurrent} concurrent...")

        while time.perf_counter() < end_time:
            # Start new workspaces up to max_concurrent
            while len(active_tasks) < max_concurrent and time.perf_counter() < end_time:
                workspace_id = f"throughput-{uuid.uuid4().hex[:8]}"
                task = asyncio.create_task(self.time_workspace_cycle(workspace_id))
                active_tasks.add(task)

            if not active_tasks:
                break

            # Wait for any task to complete
            done, active_tasks = await asyncio.wait(
                active_tasks,
                timeout=0.1,
                return_when=asyncio.FIRST_COMPLETED,
            )

            # Process completed tasks
            for task in done:
                try:
                    timing = task.result()
                    result.add_timing(timing)
                    completed_count += 1
                except Exception as e:
                    result.errors.append(str(e))

        # Wait for remaining tasks
        if active_tasks:
            self.log(f"Waiting for {len(active_tasks)} remaining tasks...")
            done, _ = await asyncio.wait(active_tasks, timeout=30)
            for task in done:
                try:
                    timing = task.result()
                    result.add_timing(timing)
                    completed_count += 1
                except Exception as e:
                    result.errors.append(str(e))

        actual_duration = time.perf_counter() - start_time
        result.iterations = completed_count
        result.duration_seconds = actual_duration
        result.workspaces_per_second = (
            completed_count / actual_duration if actual_duration > 0 else 0
        )

        result.metadata["max_concurrent"] = max_concurrent
        result.metadata["workspaces_per_minute"] = result.workspaces_per_second * 60

        result.complete()
        return result
