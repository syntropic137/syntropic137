"""CLI for Syntropic137 performance benchmarks."""

from __future__ import annotations

import asyncio
from pathlib import Path  # noqa: TC003 - needed at runtime for typer
from typing import Annotated, Any

import typer

from syn_perf.reporters import ConsoleReporter, JSONReporter

app = typer.Typer(
    name="syn-perf",
    help="Performance benchmarks for Syntropic137 isolated workspaces.",
    no_args_is_help=True,
)


def get_reporter() -> ConsoleReporter:
    """Get console reporter."""
    return ConsoleReporter()


def save_json_if_requested(result: Any, output: Path | None, reporter_type: str) -> None:
    """Save JSON report if output path provided."""
    if output:
        json_reporter = JSONReporter()
        if reporter_type == "comparison":
            report = json_reporter.generate_comparison_report(result)
        else:
            report = json_reporter.generate_report(result)
        json_reporter.save(report, output)
        typer.echo(f"Report saved to: {output}")


@app.command()
def single(
    backend: Annotated[
        str,
        typer.Option("--backend", "-b", help="Isolation backend to test"),
    ] = "docker_hardened",
    iterations: Annotated[
        int,
        typer.Option("--iterations", "-n", help="Number of iterations"),
    ] = 10,
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Verbose output"),
    ] = False,
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="JSON output file"),
    ] = None,
) -> None:
    """Run single workspace benchmark.

    Measures timing for individual workspace create/destroy cycles.
    """
    from syn_perf.benchmarks import SingleBenchmark

    async def run() -> None:
        benchmark = SingleBenchmark(backend=backend, verbose=verbose)
        result = await benchmark.run(iterations=iterations)

        reporter = get_reporter()
        reporter.report_single(result)

        save_json_if_requested(result, output, "single")

    asyncio.run(run())


@app.command()
def parallel(
    backend: Annotated[
        str,
        typer.Option("--backend", "-b", help="Isolation backend to test"),
    ] = "docker_hardened",
    count: Annotated[
        int,
        typer.Option("--count", "-n", help="Number of concurrent workspaces"),
    ] = 10,
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Verbose output"),
    ] = False,
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="JSON output file"),
    ] = None,
) -> None:
    """Run parallel scaling benchmark.

    Creates multiple workspaces concurrently and measures total time.
    """
    from syn_perf.benchmarks import ParallelBenchmark

    async def run() -> None:
        benchmark = ParallelBenchmark(backend=backend, verbose=verbose)
        result = await benchmark.run(count=count)

        reporter = get_reporter()
        reporter.report_parallel(result)

        save_json_if_requested(result, output, "parallel")

    asyncio.run(run())


@app.command()
def throughput(
    backend: Annotated[
        str,
        typer.Option("--backend", "-b", help="Isolation backend to test"),
    ] = "docker_hardened",
    duration: Annotated[
        float,
        typer.Option("--duration", "-d", help="Test duration in seconds"),
    ] = 30.0,
    concurrent: Annotated[
        int,
        typer.Option("--concurrent", "-c", help="Max concurrent workspaces"),
    ] = 5,
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Verbose output"),
    ] = False,
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="JSON output file"),
    ] = None,
) -> None:
    """Run throughput benchmark.

    Creates workspaces as fast as possible for the specified duration.
    """
    from syn_perf.benchmarks import ThroughputBenchmark

    async def run() -> None:
        benchmark = ThroughputBenchmark(backend=backend, verbose=verbose)
        result = await benchmark.run(duration=duration, max_concurrent=concurrent)

        reporter = get_reporter()
        reporter.report_throughput(result)

        save_json_if_requested(result, output, "throughput")

    asyncio.run(run())


@app.command()
def compare(
    iterations: Annotated[
        int,
        typer.Option("--iterations", "-n", help="Iterations per backend"),
    ] = 5,
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Verbose output"),
    ] = False,
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="JSON output file"),
    ] = None,
) -> None:
    """Compare all available backends.

    Runs the same benchmark on each available isolation backend.
    """
    from syn_perf.benchmarks import BackendComparison

    async def run() -> None:
        comparison = BackendComparison(verbose=verbose)
        result = await comparison.run(iterations=iterations)

        reporter = get_reporter()
        reporter.report_comparison(result)

        save_json_if_requested(result, output, "comparison")

    asyncio.run(run())


@app.command()
def check() -> None:
    """Check which backends are available."""
    from syn_perf.benchmarks import BackendComparison

    comparison = BackendComparison(verbose=True)
    available, unavailable = comparison.get_available_backends()

    console = ConsoleReporter().console

    console.print("\n[bold]Backend Availability:[/bold]\n")

    for backend in available:
        console.print(f"  [green]✓[/green] {backend}")

    for backend in unavailable:
        console.print(f"  [red]✗[/red] {backend}")

    console.print()


if __name__ == "__main__":
    app()
