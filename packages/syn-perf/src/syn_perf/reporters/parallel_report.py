"""Parallel benchmark report rendering for console output.

Extracted from ConsoleReporter to reduce module complexity.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syn_perf.metrics import TimingStats
from syn_perf.reporters.tables import format_time, print_header

if TYPE_CHECKING:
    from rich.console import Console

    from syn_perf.metrics import BenchmarkResult


def report_parallel(console: Console, result: BenchmarkResult) -> None:
    """Report parallel benchmark results."""
    print_header(console, "Parallel Scaling Benchmark")

    console.print(f"[bold]Backend:[/bold] {result.backend}")
    console.print(f"[bold]Concurrent Workspaces:[/bold] {result.concurrent_count}")
    console.print(f"[bold]Success Rate:[/bold] {result.success_rate:.1f}%")
    console.print()

    if result.total_parallel_time_ms:
        console.print("[bold]Results:[/bold]")
        console.print(f"  Total Time:        {format_time(result.total_parallel_time_ms)}")
        if "avg_per_workspace_ms" in result.metadata:
            console.print(
                f"  Avg per Workspace: {format_time(result.metadata['avg_per_workspace_ms'])}"
            )
        if "sequential_estimate_ms" in result.metadata:
            console.print(
                f"  Sequential Est.:   {format_time(result.metadata['sequential_estimate_ms'])}"
            )
        if "speedup" in result.metadata:
            console.print(f"  Speedup:           [green]{result.metadata['speedup']}x[/green]")

    console.print()

    if result.total_times_ms:
        stats = TimingStats.from_timings(result.total_times_ms)
        console.print("[bold]Individual Timings:[/bold]")
        console.print(f"  Fastest: {format_time(stats.min_ms)}")
        console.print(f"  Slowest: {format_time(stats.max_ms)}")
        console.print(f"  Std Dev: {format_time(stats.std_dev_ms)}")
        console.print()
