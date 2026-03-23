"""Shared Rich table builders for benchmark reports."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.panel import Panel
from rich.table import Table

from syn_perf.metrics import TimingStats

if TYPE_CHECKING:
    from rich.console import Console

    from syn_perf.metrics import BenchmarkResult


def format_time(ms: float) -> str:
    """Format milliseconds for display."""
    if ms == 0:
        return "-"
    if ms < 1000:
        return f"{ms:.0f}ms"
    return f"{ms / 1000:.2f}s"


def print_header(console: Console, title: str) -> None:
    """Print a styled benchmark section header."""
    console.print()
    console.print(Panel.fit(f"[bold cyan]{title}[/bold cyan]", border_style="cyan"))
    console.print()


def build_timing_table(result: BenchmarkResult) -> Table:
    """Build a Rich table with create/destroy/total timing statistics."""
    table = Table(title="Timing Statistics")
    table.add_column("Metric", style="cyan")
    table.add_column("Min", justify="right")
    table.add_column("Max", justify="right")
    table.add_column("Mean", justify="right")
    table.add_column("P95", justify="right")
    table.add_column("P99", justify="right")

    for label, timings in [
        ("Create Time", result.create_times_ms),
        ("Destroy Time", result.destroy_times_ms),
        ("Total Cycle", result.total_times_ms),
    ]:
        stats = TimingStats.from_timings(timings)
        table.add_row(
            label,
            format_time(stats.min_ms),
            format_time(stats.max_ms),
            format_time(stats.mean_ms),
            format_time(stats.p95_ms),
            format_time(stats.p99_ms),
        )

    return table
