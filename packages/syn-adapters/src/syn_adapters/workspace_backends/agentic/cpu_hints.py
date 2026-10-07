"""Tell build and test tools how many CPUs a workspace really has.

WHY. `--cpus=N` sets a CFS quota (`cpu.max`) and nothing else, so inside the
container `nproc`, `os.cpu_count()` and `sched_getaffinity` all still report
every host core. Measured on the production host (16 cores, limit 4, 8
concurrent workspaces): each workspace saw 16, so `pytest -n auto`, vitest,
cargo and make each started 16 workers inside a 4-CPU quota. Load average
reached ~30, agent output stalled for minutes and a verify stream died.

`--cpuset-cpus` would make `nproc` honest without any of this, but it pins a
container to fixed cores, cannot express a fractional limit, needs a host-wide
allocator shared by every concurrent workspace, and strands idle cores that
the quota would let a busy neighbour use. Until such an allocator exists,
each tool is told the number directly.
"""

from __future__ import annotations

import math
from collections.abc import Mapping


def cpu_concurrency_env(cpu_limit_cores: float | None) -> dict[str, str]:
    """Environment that sizes common tools to `cpu_limit_cores`, rounded up.

    No limit (``None``, or a non-positive value, which Docker reads as
    unlimited) yields an empty mapping: the tools' own detection is then right.

    Each variable is one a tool reads at the version we can verify:
    vitest 4 reads only ``VITEST_MAX_WORKERS`` - ``VITEST_MAX_THREADS`` and
    ``VITEST_MAX_FORKS`` were dropped, so they are deliberately absent.
    ``NODE_OPTIONS`` is left alone; it does not control worker counts.
    """
    if cpu_limit_cores is None or cpu_limit_cores <= 0:
        return {}
    n = str(max(1, math.ceil(cpu_limit_cores)))
    return {
        "PYTEST_XDIST_AUTO_NUM_WORKERS": n,
        "VITEST_MAX_WORKERS": n,
        "CARGO_BUILD_JOBS": n,
        "MAKEFLAGS": f"-j{n}",
        "UV_CONCURRENT_BUILDS": n,
        "OMP_NUM_THREADS": n,
        "RAYON_NUM_THREADS": n,
    }


def with_cpu_hints(environment: Mapping[str, str], cpu_limit_cores: float | None) -> dict[str, str]:
    """`environment` plus the CPU hints it does not already set.

    A key the workflow or phase set explicitly is kept as-is, even an empty
    value: an operator who wrote ``MAKEFLAGS=`` meant it.
    """
    return cpu_concurrency_env(cpu_limit_cores) | dict(environment)
