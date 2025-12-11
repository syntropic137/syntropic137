"""AEF Performance Benchmarking Suite.

Provides performance benchmarks for isolated workspace operations:
- Single workspace timing
- Parallel scaling tests
- Throughput measurements
- Backend comparisons

Usage:
    # CLI
    uv run python -m aef_perf single --iterations 10
    uv run python -m aef_perf parallel --count 10
    uv run python -m aef_perf compare

    # Programmatic
    from aef_perf import SingleBenchmark, ParallelBenchmark

    benchmark = SingleBenchmark(backend="docker_hardened")
    results = await benchmark.run(iterations=10)
    print(results.summary())
"""

from aef_perf.benchmarks import (
    BackendComparison,
    ParallelBenchmark,
    SingleBenchmark,
    ThroughputBenchmark,
)
from aef_perf.metrics import BenchmarkResult, TimingStats

__all__ = [
    "BackendComparison",
    "BenchmarkResult",
    "ParallelBenchmark",
    "SingleBenchmark",
    "ThroughputBenchmark",
    "TimingStats",
]

__version__ = "0.1.0"
