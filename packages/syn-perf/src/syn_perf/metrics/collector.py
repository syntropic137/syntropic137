"""Timing data collection for benchmarks."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class WorkspaceTiming:
    """Timing data for a single workspace lifecycle."""

    workspace_id: str
    backend: str
    create_time_ms: float
    destroy_time_ms: float
    total_time_ms: float
    success: bool
    error: str | None = None
    started_at: datetime = field(default_factory=datetime.utcnow)

    @property
    def create_time_seconds(self) -> float:
        """Create time in seconds."""
        return self.create_time_ms / 1000

    @property
    def destroy_time_seconds(self) -> float:
        """Destroy time in seconds."""
        return self.destroy_time_ms / 1000

    @property
    def total_time_seconds(self) -> float:
        """Total time in seconds."""
        return self.total_time_ms / 1000


@dataclass
class BenchmarkResult:
    """Result of a benchmark run."""

    benchmark_type: str  # single, parallel, throughput, compare
    backend: str
    iterations: int
    timings: list[WorkspaceTiming] = field(default_factory=list)
    started_at: datetime = field(default_factory=datetime.utcnow)
    completed_at: datetime | None = None

    # Parallel-specific
    concurrent_count: int | None = None
    total_parallel_time_ms: float | None = None

    # Throughput-specific
    duration_seconds: float | None = None
    workspaces_per_second: float | None = None

    # Metadata
    errors: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    def add_timing(self, timing: WorkspaceTiming) -> None:
        """Add a timing measurement."""
        self.timings.append(timing)
        if not timing.success and timing.error:
            self.errors.append(timing.error)

    def complete(self) -> None:
        """Mark the benchmark as complete."""
        self.completed_at = datetime.utcnow()

    @property
    def success_count(self) -> int:
        """Number of successful workspace cycles."""
        return sum(1 for t in self.timings if t.success)

    @property
    def failure_count(self) -> int:
        """Number of failed workspace cycles."""
        return sum(1 for t in self.timings if not t.success)

    @property
    def success_rate(self) -> float:
        """Success rate as percentage."""
        if not self.timings:
            return 0.0
        return (self.success_count / len(self.timings)) * 100

    @property
    def create_times_ms(self) -> list[float]:
        """List of successful create times in ms."""
        return [t.create_time_ms for t in self.timings if t.success]

    @property
    def destroy_times_ms(self) -> list[float]:
        """List of successful destroy times in ms."""
        return [t.destroy_time_ms for t in self.timings if t.success]

    @property
    def total_times_ms(self) -> list[float]:
        """List of successful total times in ms."""
        return [t.total_time_ms for t in self.timings if t.success]

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON export."""
        return {
            "benchmark_type": self.benchmark_type,
            "backend": self.backend,
            "iterations": self.iterations,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "success_rate": self.success_rate,
            "concurrent_count": self.concurrent_count,
            "total_parallel_time_ms": self.total_parallel_time_ms,
            "duration_seconds": self.duration_seconds,
            "workspaces_per_second": self.workspaces_per_second,
            "timings": [
                {
                    "workspace_id": t.workspace_id,
                    "backend": t.backend,
                    "create_time_ms": t.create_time_ms,
                    "destroy_time_ms": t.destroy_time_ms,
                    "total_time_ms": t.total_time_ms,
                    "success": t.success,
                    "error": t.error,
                }
                for t in self.timings
            ],
            "errors": self.errors,
            "metadata": self.metadata,
        }
