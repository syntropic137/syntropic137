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

## Token-free load test (#1717)

```bash
SYN_API_URL=http://localhost:18000 uv run python -m syn_perf.loadtest --n 20 --tier platform \
  --streams streams.json --fixture-repo <owner>/<loadtest-fixture> \
  --api-container syn-api --postgres-container syn-db \
  --event-store-container syn-event-store --socket-proxy-container syn-socket-proxy
```

`streams.json` maps every phase id of `workflows/sdlc/implement-v3/workflow.yaml`
to a `ScriptedStream` (recording, harness, CLI version, tool-use count). The
driver writes the validated profile to `--profile-out` for the stack's
workspaces, admits N executions over `--admit-seconds` (each start carries
`--fixture-repo` in its typed `repos` field) while sampling every
`--sample-seconds`, keeps sampling for `--sustain-seconds`, drains, and writes
the report. The API URL is `--api-url`, else `$SYN_API_URL`, else the selfhost
gateway default.

The defaults are the north-star bar (reads under 0.5 s, admission within 300 s,
held 1800 s). Any looser figure fails the `north_star_bar` check, so a short
or relaxed run reports what it measured without certifying anything. Each tick
times the dashboard's own list read (`/executions?page=1&page_size=50`) and
every detail read. All four container roles must be sampled, or
`container_stats` names the missing roles.

It requires a stack whose workspace image is the stub agent
(AgentParadise/agentic-workspace#44). Concurrency is the count of phases the
server reports `running` whose session is `running` with `agent_launch:
launched` (the server's `AgentLaunched` fact), never the executions submitted
and never a phase still provisioning. Event counts hold every planned phase to its scripted tool-use
count in starts AND completions, counting Agent/Task uses the timeline
relabels as subagent operations. Exit 0: pass bar held; 1: a check failed
(named in the report); 2: refused. A session reporting a model other than
`syn-scripted-agent` stops further admissions and the run, and the report is
still written; a session that never reports the scripted model fails the
`scripted` check.
