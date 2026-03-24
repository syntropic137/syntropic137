"""Console reporter with rich terminal tables."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.console import Console

from syn_perf.reporters.comparison_report import report_comparison
from syn_perf.reporters.parallel_report import report_parallel
from syn_perf.reporters.tables import build_timing_table, print_header

if TYPE_CHECKING:
    from syn_perf.benchmarks.compare_result import BackendComparisonResult
    from syn_perf.metrics import BenchmarkResult


class ConsoleReporter:
    """Generate rich terminal output for benchmark results."""

    def __init__(self) -> None:
        self.console = Console()

    def report_single(self, result: BenchmarkResult) -> None:
        """Report single benchmark results."""
        print_header(self.console, "Workspace Performance Benchmark")

        self.console.print(f"[bold]Backend:[/bold] {result.backend}")
        self.console.print(f"[bold]Iterations:[/bold] {result.iterations}")
        self.console.print(f"[bold]Success Rate:[/bold] {result.success_rate:.1f}%")
        self.console.print()

        if not result.total_times_ms:
            self.console.print("[red]No successful measurements[/red]")
            return

        self.console.print(build_timing_table(result))
        self.console.print()

    def report_parallel(self, result: BenchmarkResult) -> None:
        """Report parallel benchmark results."""
        report_parallel(self.console, result)

    def report_throughput(self, result: BenchmarkResult) -> None:
        """Report throughput benchmark results."""
        print_header(self.console, "Throughput Benchmark")

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
        report_comparison(self.console, result)
