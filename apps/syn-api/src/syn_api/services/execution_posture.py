"""The startup posture of the execution budget (#1557)."""

from __future__ import annotations

import logging
from pathlib import Path

from syn_shared.env_constants import (
    ENV_SYN_EXECUTION_MAX_CONCURRENT,
    ENV_SYN_POLLING_MAX_CONCURRENT_DISPATCHES,
)
from syn_shared.settings.execution import (
    API_BASELINE_MEMORY_MIB,
    EXECUTION_API_MEMORY_MIB,
    executions_that_fit,
)

logger = logging.getLogger(__name__)


#: Where the kernel states this process's memory limit, cgroup v2 then v1.
_CGROUP_MEMORY_LIMITS = (
    Path("/sys/fs/cgroup/memory.max"),
    Path("/sys/fs/cgroup/memory/memory.limit_in_bytes"),
)

#: A v1 "limit" this large means no limit was set.
_UNLIMITED_BYTES = 1 << 60


def api_memory_limit_mib() -> int | None:
    """This process's container memory limit in MiB, or None if none is readable.

    The API_MEMORY_LIMIT compose sets is not in the container's environment; the
    cgroup the kernel enforces it through is, so that is what is read.
    """
    for path in _CGROUP_MEMORY_LIMITS:
        try:
            raw = path.read_text().strip()
        except OSError:
            continue
        if not raw.isdigit():  # "max": unlimited
            return None
        limit = int(raw)
        return None if limit >= _UNLIMITED_BYTES else limit // (1024 * 1024)
    return None


def log_execution_concurrency_posture(
    max_concurrent: int,
    *,
    memory_limit_mib: int | None,
    retired_setting: str | None,
) -> None:
    """Say, once at startup, how many executions may run and whether that fits.

    Reported where the settings are read, not while constructing the
    dispatcher, so it is said once and on every startup path.

    The hazard is capacity, not isolation (#1557). Concurrent executions once
    shared processor state (#865), which is why the old limit was 1; #1311
    gave each execution its own. What still breaks is memory: every running
    execution costs the API ~96MiB, and past its limit the kernel kills the
    API and every in-flight execution with it (#1552). So this warns when the
    budget does not fit the limit the kernel is enforcing.
    """
    logger.info(
        "Execution budget: %d concurrent executions across direct, trigger and "
        "resume starts (%s); further starts queue visibly.",
        max_concurrent,
        ENV_SYN_EXECUTION_MAX_CONCURRENT,
    )
    if retired_setting is not None:
        logger.warning(
            "%s=%s is IGNORED: it was replaced by %s, one limit for every start "
            "path (#1557). Remove it, and set %s instead if you need a value "
            "other than the default.",
            ENV_SYN_POLLING_MAX_CONCURRENT_DISPATCHES,
            retired_setting,
            ENV_SYN_EXECUTION_MAX_CONCURRENT,
            ENV_SYN_EXECUTION_MAX_CONCURRENT,
        )
    if memory_limit_mib is None:
        return
    fits = executions_that_fit(memory_limit_mib)
    if max_concurrent > fits:
        logger.warning(
            "%s is %d but this API's %dMiB memory limit fits about %d "
            "(%dMiB baseline + %dMiB per execution). Past it the kernel "
            "OOM-kills the API and every in-flight execution with it (#1552). "
            "Lower %s or raise API_MEMORY_LIMIT.",
            ENV_SYN_EXECUTION_MAX_CONCURRENT,
            max_concurrent,
            memory_limit_mib,
            fits,
            API_BASELINE_MEMORY_MIB,
            EXECUTION_API_MEMORY_MIB,
            ENV_SYN_EXECUTION_MAX_CONCURRENT,
        )
