"""Tell build and test tools how many CPUs a workspace really has.

WHY. `--cpus=N` sets only a CFS quota (`cpu.max`); it leaves CPU affinity
alone. Inside a 4-CPU workspace on a 16-core host, `nproc`, `os.cpu_count()`
and `sched_getaffinity` all report 16, so `pytest -n auto`, vitest, cargo and
make each start 16 workers against a quota of 4. Measured on production
2026-10-07 with 8 concurrent workspaces: host load ~30 on 16 cores, agent
output stalled for minutes, and a verify stream died mid-run.

`--cpuset-cpus` would make `nproc` honest, but it pins each container to fixed
cores and needs a host-wide allocator, which does not exist. Until it does,
these variables are the hint every common tool reads instead.
"""

from __future__ import annotations

import math
from collections.abc import Mapping


def cpu_hint_env(cpu_limit_cores: float | None) -> dict[str, str]:
    """The worker-count variables for a workspace limited to `cpu_limit_cores`.

    N is the limit rounded up, at least 1: a 2.5-CPU quota can usefully run
    three workers, and none is never right. No limit (None, or 0, which Docker
    reads as unlimited) gives no hints, because the tools' own detection is then
    correct.

    `NODE_OPTIONS` is deliberately absent: it carries unrelated flags a phase
    may set, and node has no worker-count option there to set anyway.
    """
    if not cpu_limit_cores or cpu_limit_cores <= 0:
        return {}
    n = str(max(1, math.ceil(cpu_limit_cores)))
    return {
        "PYTEST_XDIST_AUTO_NUM_WORKERS": n,  # what `pytest -n auto` resolves to
        "CARGO_BUILD_JOBS": n,
        "MAKEFLAGS": f"-j{n}",
        "VITEST_MAX_WORKERS": n,  # vitest 4.x
        "VITEST_MAX_THREADS": n,  # vitest <= 3.x, threads pool
        "VITEST_MAX_FORKS": n,  # vitest <= 3.x, forks pool
        "UV_CONCURRENT_BUILDS": n,
        "OMP_NUM_THREADS": n,
        "RAYON_NUM_THREADS": n,
    }


def with_cpu_hints(environment: Mapping[str, str], cpu_limit_cores: float | None) -> dict[str, str]:
    """`environment` plus the CPU hints it does not already set.

    A value the workflow or phase sets explicitly wins: these are defaults
    sized to the quota, not policy. An empty value is not a choice, matching
    how TMPDIR and the cache variables are defaulted beside this.
    """
    resolved = dict(environment)
    for key, value in cpu_hint_env(cpu_limit_cores).items():
        if not resolved.get(key):
            resolved[key] = value
    return resolved
