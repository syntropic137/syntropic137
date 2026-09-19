"""Syntropic137 Performance Benchmarking Suite.

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

#: NO ``__version__`` HERE. This package had one, hardcoded "0.1.0", while its
#: pyproject.toml said 0.29.0 - a second home for the release number that
#: `just bump-version` does not write and therefore could only ever be wrong.
#: That is the drift #1380 is about; the packages that must REPORT a running
#: build (syn-api, syn-collector) read it from importlib.metadata through one
#: accessor, and a library that reports nothing does not need a copy at all.
