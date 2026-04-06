"""Backend comparison benchmark."""

from __future__ import annotations

from syn_perf.benchmarks.compare_result import BackendComparisonResult
from syn_perf.benchmarks.single import SingleBenchmark


class BackendComparison:
    """Compare performance across all available backends.

    Runs the same benchmark on each available backend and
    produces a comparison report.

    Usage:
        comparison = BackendComparison()
        result = await comparison.run(iterations=5)
        print(f"Best backend: {result.best_backend}")
    """

    # All backends to try
    ALL_BACKENDS: list[str] = [
        "firecracker",
        "gvisor",
        "docker_hardened",
        "cloud",
    ]

    def __init__(self, verbose: bool = False) -> None:
        """Initialize comparison.

        Args:
            verbose: Enable verbose output
        """
        self.verbose = verbose

    def log(self, msg: str) -> None:
        """Log if verbose."""
        if self.verbose:
            print(f"  [DEBUG] {msg}")

    def get_available_backends(self) -> tuple[list[str], list[str]]:
        """Check which backends are available.

        Returns:
            Tuple of (available, unavailable) backend names
        """
        from syn_adapters.workspaces import (
            E2BWorkspace,
            FirecrackerWorkspace,
            GVisorWorkspace,
            HardenedDockerWorkspace,
        )

        backend_classes = {
            "firecracker": FirecrackerWorkspace,
            "gvisor": GVisorWorkspace,
            "docker_hardened": HardenedDockerWorkspace,
            "cloud": E2BWorkspace,
        }

        available = []
        unavailable = []

        for name, cls in backend_classes.items():
            if cls.is_available():
                available.append(name)
                self.log(f"Backend {name}: available")
            else:
                unavailable.append(name)
                self.log(f"Backend {name}: not available")

        return available, unavailable

    async def run(self, iterations: int = 5) -> BackendComparisonResult:
        """Run comparison across all available backends.

        Args:
            iterations: Number of cycles per backend

        Returns:
            BackendComparisonResult with comparison data
        """
        result = BackendComparisonResult()

        available, unavailable = self.get_available_backends()
        result.available_backends = available
        result.unavailable_backends = unavailable

        if not available:
            self.log("No backends available!")
            return result

        best_mean_total = float("inf")
        best_backend = None

        for backend in available:
            self.log(f"Benchmarking {backend}...")

            benchmark = SingleBenchmark(backend=backend, verbose=self.verbose)
            try:
                bench_result = await benchmark.run(iterations=iterations)
                result.add_result(backend, bench_result)

                # Track best
                stats = result.get_stats(backend)
                if stats and stats["total"].mean_ms < best_mean_total:
                    best_mean_total = stats["total"].mean_ms
                    best_backend = backend

            except Exception as e:
                self.log(f"Backend {backend} failed: {e}")
                result.unavailable_backends.append(backend)
                result.available_backends.remove(backend)

        result.best_backend = best_backend
        return result
