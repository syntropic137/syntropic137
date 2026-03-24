"""Benchmark implementations."""

from syn_perf.benchmarks.compare import BackendComparison
from syn_perf.benchmarks.compare_result import BackendComparisonResult
from syn_perf.benchmarks.parallel import ParallelBenchmark
from syn_perf.benchmarks.single import SingleBenchmark
from syn_perf.benchmarks.throughput import ThroughputBenchmark

__all__ = [
    "BackendComparison",
    "BackendComparisonResult",
    "ParallelBenchmark",
    "SingleBenchmark",
    "ThroughputBenchmark",
]
