"""Console reporter with rich terminal tables."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from syn_perf.metrics import TimingStats

if TYPE_CHECKING:
    from syn_perf.benchmarks.compare import BackendComparisonResult
    from syn_perf.metrics import BenchmarkResult


class ConsoleReporter:
    """Generate rich terminal output for benchmark results."""

    def __init__(self) -> None:
        self.console = Console()

    def _format_time(self, ms: float) -> str:
        """Format milliseconds for display."""
        if ms == 0:
            return "-"
        if ms < 1000:
            return f"{ms:.0f}ms"
        return f"{ms / 1000:.2f}s"

    def report_single(self, result: BenchmarkResult) -> None:
        """Report single benchmark results."""
        self.console.print()
        self.console.print(
            Panel.fit(
                "[bold cyan]Workspace Performance Benchmark[/bold cyan]",
                border_style="cyan",
            )
        )
        self.console.print()

        # Info
        self.console.print(f"[bold]Backend:[/bold] {result.backend}")
        self.console.print(f"[bold]Iterations:[/bold] {result.iterations}")
        self.console.print(f"[bold]Success Rate:[/bold] {result.success_rate:.1f}%")
        self.console.print()

        if not result.total_times_ms:
            self.console.print("[red]No successful measurements[/red]")
            return

        # Statistics table
        table = Table(title="Timing Statistics")
        table.add_column("Metric", style="cyan")
        table.add_column("Min", justify="right")
        table.add_column("Max", justify="right")
        table.add_column("Mean", justify="right")
        table.add_column("P95", justify="right")
        table.add_column("P99", justify="right")

        create_stats = TimingStats.from_timings(result.create_times_ms)
        destroy_stats = TimingStats.from_timings(result.destroy_times_ms)
        total_stats = TimingStats.from_timings(result.total_times_ms)

        table.add_row(
            "Create Time",
            self._format_time(create_stats.min_ms),
            self._format_time(create_stats.max_ms),
            self._format_time(create_stats.mean_ms),
            self._format_time(create_stats.p95_ms),
            self._format_time(create_stats.p99_ms),
        )
        table.add_row(
            "Destroy Time",
            self._format_time(destroy_stats.min_ms),
            self._format_time(destroy_stats.max_ms),
            self._format_time(destroy_stats.mean_ms),
            self._format_time(destroy_stats.p95_ms),
            self._format_time(destroy_stats.p99_ms),
        )
        table.add_row(
            "Total Cycle",
            self._format_time(total_stats.min_ms),
            self._format_time(total_stats.max_ms),
            self._format_time(total_stats.mean_ms),
            self._format_time(total_stats.p95_ms),
            self._format_time(total_stats.p99_ms),
        )

        self.console.print(table)
        self.console.print()

    def report_parallel(self, result: BenchmarkResult) -> None:
        """Report parallel benchmark results."""
        self.console.print()
        self.console.print(
            Panel.fit(
                "[bold cyan]Parallel Scaling Benchmark[/bold cyan]",
                border_style="cyan",
            )
        )
        self.console.print()

        # Info
        self.console.print(f"[bold]Backend:[/bold] {result.backend}")
        self.console.print(f"[bold]Concurrent Workspaces:[/bold] {result.concurrent_count}")
        self.console.print(f"[bold]Success Rate:[/bold] {result.success_rate:.1f}%")
        self.console.print()

        if result.total_parallel_time_ms:
            self.console.print("[bold]Results:[/bold]")
            self.console.print(
                f"  Total Time:        {self._format_time(result.total_parallel_time_ms)}"
            )

            if "avg_per_workspace_ms" in result.metadata:
                self.console.print(
                    f"  Avg per Workspace: {self._format_time(result.metadata['avg_per_workspace_ms'])}"
                )

            if "sequential_estimate_ms" in result.metadata:
                self.console.print(
                    f"  Sequential Est.:   {self._format_time(result.metadata['sequential_estimate_ms'])}"
                )

            if "speedup" in result.metadata:
                speedup = result.metadata["speedup"]
                self.console.print(f"  Speedup:           [green]{speedup}x[/green]")

        self.console.print()

        # Individual timings
        if result.total_times_ms:
            stats = TimingStats.from_timings(result.total_times_ms)
            self.console.print("[bold]Individual Timings:[/bold]")
            self.console.print(f"  Fastest: {self._format_time(stats.min_ms)}")
            self.console.print(f"  Slowest: {self._format_time(stats.max_ms)}")
            self.console.print(f"  Std Dev: {self._format_time(stats.std_dev_ms)}")
            self.console.print()

    def report_throughput(self, result: BenchmarkResult) -> None:
        """Report throughput benchmark results."""
        self.console.print()
        self.console.print(
            Panel.fit(
                "[bold cyan]Throughput Benchmark[/bold cyan]",
                border_style="cyan",
            )
        )
        self.console.print()

        # Info
        self.console.print(f"[bold]Backend:[/bold] {result.backend}")
        self.console.print(f"[bold]Duration:[/bold] {result.duration_seconds:.1f}s")
        self.console.print(f"[bold]Completed:[/bold] {result.iterations} workspaces")
        self.console.print(f"[bold]Success Rate:[/bold] {result.success_rate:.1f}%")
        self.console.print()

        if result.workspaces_per_second:
            self.console.print("[bold]Throughput:[/bold]")
            self.console.print(f"  Per Second: [green]{result.workspaces_per_second:.2f}[/green]")
            if "workspaces_per_minute" in result.metadata:
                self.console.print(
                    f"  Per Minute: [green]{result.metadata['workspaces_per_minute']:.1f}[/green]"
                )
            self.console.print()

    def report_comparison(self, result: BackendComparisonResult) -> None:
        """Report backend comparison results."""
        self.console.print()
        self.console.print(
            Panel.fit(
                "[bold cyan]Backend Comparison[/bold cyan]",
                border_style="cyan",
            )
        )
        self.console.print()

        # Available backends
        if result.unavailable_backends:
            self.console.print(f"[dim]Unavailable: {', '.join(result.unavailable_backends)}[/dim]")
            self.console.print()

        if not result.available_backends:
            self.console.print("[red]No backends available for testing[/red]")
            return

        # Comparison table
        table = Table(title="Performance Comparison")
        table.add_column("Backend", style="cyan")
        table.add_column("Create", justify="right")
        table.add_column("Destroy", justify="right")
        table.add_column("Total", justify="right")
        table.add_column("Success", justify="right")

        for backend in result.available_backends:
            stats = result.get_stats(backend)
            bench_result = result.results.get(backend)

            if stats and bench_result:
                is_best = backend == result.best_backend
                style = "bold green" if is_best else None

                table.add_row(
                    f"{'★ ' if is_best else ''}{backend}",
                    self._format_time(stats["create"].mean_ms),
                    self._format_time(stats["destroy"].mean_ms),
                    self._format_time(stats["total"].mean_ms),
                    f"{bench_result.success_rate:.0f}%",
                    style=style,
                )

        self.console.print(table)
        self.console.print()

        if result.best_backend:
            self.console.print(f"[bold green]Recommended: {result.best_backend}[/bold green]")
            self.console.print()
