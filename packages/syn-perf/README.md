# Syntropic137 Performance Benchmarks

Performance benchmarking suite for Syntropic137 isolated workspaces.

## Installation

This package is part of the Syntropic137 monorepo workspace.

```bash
uv sync
```

## Usage

### CLI

```bash
# Single workspace timing (10 iterations)
uv run python -m syn_perf single --iterations 10

# Parallel scaling (10 concurrent workspaces)
uv run python -m syn_perf parallel --count 10

# Throughput test (30 seconds)
uv run python -m syn_perf throughput --duration 30

# Compare all backends
uv run python -m syn_perf compare

# Check available backends
uv run python -m syn_perf check

# Save results to JSON
uv run python -m syn_perf single --output results.json
```

### Programmatic

```python
from syn_perf import SingleBenchmark, ParallelBenchmark

# Single workspace benchmark
benchmark = SingleBenchmark(backend="docker_hardened")
result = await benchmark.run(iterations=10)
print(f"Mean create time: {result.create_times_ms}")

# Parallel benchmark
parallel = ParallelBenchmark(backend="docker_hardened")
result = await parallel.run(count=10)
print(f"Speedup: {result.metadata['speedup']}x")
```

## Benchmarks

### Single Workspace
Measures individual workspace create/destroy cycles.

### Parallel Scaling
Creates N workspaces concurrently and measures total time and speedup.

### Throughput
Creates workspaces as fast as possible for a fixed duration.

### Backend Comparison
Runs the same benchmark on all available backends.

## Output

Results are displayed in rich terminal tables and can be exported to JSON.

```
╔══════════════════════════════════════════════════════════════╗
║           Workspace Performance Benchmark                     ║
╚══════════════════════════════════════════════════════════════╝

Backend: docker_hardened
Iterations: 10

┌────────────────┬─────────┬─────────┬─────────┬─────────┬─────────┐
│ Metric         │ Min     │ Max     │ Mean    │ P95     │ P99     │
├────────────────┼─────────┼─────────┼─────────┼─────────┼─────────┤
│ Create Time    │ 1.21s   │ 2.14s   │ 1.52s   │ 1.98s   │ 2.10s   │
│ Destroy Time   │ 0.31s   │ 0.52s   │ 0.38s   │ 0.49s   │ 0.51s   │
│ Total Cycle    │ 1.55s   │ 2.61s   │ 1.90s   │ 2.42s   │ 2.58s   │
└────────────────┴─────────┴─────────┴─────────┴─────────┴─────────┘
```
