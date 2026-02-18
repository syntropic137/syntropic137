"""AEF Performance Benchmarking Suite.

Provides performance benchmarks for isolated workspace operations:
- Single workspace timing
- Parallel scaling tests
- Throughput measurements
- Backend comparisons

Usage:
    # CLI
    uv run python -m syn_perf single --iterations 10
    uv run python -m syn_perf parallel --count 10
    uv run python -m syn_perf compare

    # Programmatic
    from syn_perf import SingleBenchmark, ParallelBenchmark

    benchmark = SingleBenchmark(backend="docker_hardened")
    results = await benchmark.run(iterations=10)
    print(results.summary())
"""

from syn_perf.benchmarks import (
    BackendComparison,
    ParallelBenchmark,
    SingleBenchmark,
    ThroughputBenchmark,
)
from syn_perf.metrics import BenchmarkResult, TimingStats

__all__ = [
    "BackendComparison",
    "BenchmarkResult",
    "ParallelBenchmark",
    "SingleBenchmark",
    "ThroughputBenchmark",
    "TimingStats",
]

__version__ = "0.1.0"
