"""Data model for backend comparison results."""

from __future__ import annotations

from dataclasses import dataclass, field

from syn_perf.metrics import BenchmarkResult, TimingStats


@dataclass
class BackendComparisonResult:
    """Result of comparing multiple backends."""

    results: dict[str, BenchmarkResult] = field(default_factory=dict)
    available_backends: list[str] = field(default_factory=list)
    unavailable_backends: list[str] = field(default_factory=list)
    best_backend: str | None = None

    def add_result(self, backend: str, result: BenchmarkResult) -> None:
        """Add a backend result."""
        self.results[backend] = result

    def get_stats(self, backend: str) -> dict[str, TimingStats]:
        """Get timing stats for a backend."""
        result = self.results.get(backend)
        if not result:
            return {}

        return {
            "create": TimingStats.from_timings(result.create_times_ms),
            "destroy": TimingStats.from_timings(result.destroy_times_ms),
            "total": TimingStats.from_timings(result.total_times_ms),
        }

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "available_backends": self.available_backends,
            "unavailable_backends": self.unavailable_backends,
            "best_backend": self.best_backend,
            "results": {backend: result.to_dict() for backend, result in self.results.items()},
        }
