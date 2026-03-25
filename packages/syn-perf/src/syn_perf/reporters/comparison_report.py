"""Comparison report rendering for console output.

Extracted from ConsoleReporter to reduce module complexity.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.table import Table

from syn_perf.reporters.tables import format_time, print_header

if TYPE_CHECKING:
    from rich.console import Console

    from syn_perf.benchmarks.compare_result import BackendComparisonResult


def _add_backend_row(
    table: Table,
    backend: str,
    result: BackendComparisonResult,
) -> None:
    """Add a single backend row to the comparison table."""
    stats = result.get_stats(backend)
    bench_result = result.results.get(backend)
    if not (stats and bench_result):
        return
    is_best = backend == result.best_backend
    prefix = "★ " if is_best else ""
    table.add_row(
        f"{prefix}{backend}",
        format_time(stats["create"].mean_ms),
        format_time(stats["destroy"].mean_ms),
        format_time(stats["total"].mean_ms),
        f"{bench_result.success_rate:.0f}%",
        style="bold green" if is_best else None,
    )


def report_comparison(console: Console, result: BackendComparisonResult) -> None:
    """Report backend comparison results."""
    print_header(console, "Backend Comparison")

    if result.unavailable_backends:
        console.print(f"[dim]Unavailable: {', '.join(result.unavailable_backends)}[/dim]")
        console.print()

    if not result.available_backends:
        console.print("[red]No backends available for testing[/red]")
        return

    table = Table(title="Performance Comparison")
    table.add_column("Backend", style="cyan")
    table.add_column("Create", justify="right")
    table.add_column("Destroy", justify="right")
    table.add_column("Total", justify="right")
    table.add_column("Success", justify="right")

    for backend in result.available_backends:
        _add_backend_row(table, backend, result)

    console.print(table)
    console.print()

    if result.best_backend:
        console.print(f"[bold green]Recommended: {result.best_backend}[/bold green]")
        console.print()
