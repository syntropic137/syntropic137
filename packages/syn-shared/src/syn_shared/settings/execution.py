"""Execution settings: how many workflow executions one API process runs (#1557).

See ADR-004 (settings) and ADR-060 (admission and dispatch limits).
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from syn_shared.env_constants import ENV_SYN_EXECUTION_MAX_CONCURRENT

#: The default execution budget, and the arithmetic behind it.
#:
#: Each running execution costs the API process roughly
#: `EXECUTION_API_MEMORY_MIB` of memory on top of a `API_BASELINE_MEMORY_MIB`
#: baseline: stream parsing, transcript buffers and artifact collection all
#: happen in the API, not the workspace. Measured in #1552: 8 concurrent
#: executions held ~443MB anon RSS against what was then a 512m
#: `API_MEMORY_LIMIT` default and the kernel OOM-killed the API, which orphaned
#: all 8. The limit now defaults to 2g. At 4 the estimate is 128 + 4 x 96 =
#: 512MiB worst case, a quarter of it; the per-run slope behind a higher default
#: has not been measured yet (#1552), so the budget did not move with the limit.
DEFAULT_MAX_CONCURRENT_EXECUTIONS = 4

#: Read as SYN_EXECUTION_INTERRUPT_BUDGET_S. #1310 spells it
#: SYN_INTERRUPT_BUDGET_S; the env prefix is kept because `.env.example` and the
#: compose forwarding are generated from prefix + field name, and an alias they
#: do not see would be a knob documented under a name nothing reads.
#: How long a shutdown waits, per running execution, to save its work and record
#: it INTERRUPTED (#1381). Room for the salvage push (bounded at 20 s by
#: `REMOTE_TIMEOUT_SECONDS`), its workflow-safe retry, and the event append.
DEFAULT_INTERRUPT_BUDGET_SECONDS = 60.0

#: Rough per-execution and baseline API memory, used to size the budget against
#: `API_MEMORY_LIMIT` and to warn at startup when the two disagree. Deliberately
#: pessimistic (measured ~40-55MiB per execution in #1552).
EXECUTION_API_MEMORY_MIB = 96
API_BASELINE_MEMORY_MIB = 128


def executions_that_fit(memory_limit_mib: int) -> int:
    """How many concurrent executions an API memory limit can hold, at least 1."""
    return max(1, (memory_limit_mib - API_BASELINE_MEMORY_MIB) // EXECUTION_API_MEMORY_MIB)


class ExecutionSettings(BaseSettings):
    """The execution concurrency budget. Override via ``SYN_EXECUTION_*``."""

    model_config = SettingsConfigDict(
        env_prefix="SYN_EXECUTION_",
        env_file=".env",
        extra="ignore",
    )

    max_concurrent: int = Field(
        default=DEFAULT_MAX_CONCURRENT_EXECUTIONS,
        ge=1,
        validation_alias=ENV_SYN_EXECUTION_MAX_CONCURRENT,
        description=(
            "How many workflow executions this API process runs at once, across "
            "EVERY start path: POST /workflows/{id}/execute, trigger dispatch and "
            "resume. Further starts wait in a FIFO queue and show as status "
            "'queued' with their position (syn execution show). Per process, not "
            "per cluster. "
            "What high concurrency costs is CAPACITY: every running execution "
            "holds a workspace container (SYN_WORKSPACE_MEMORY_LIMIT_MB, default "
            "4096, and SYN_WORKSPACE_CPU_LIMIT each) and about 96MiB of API memory for "
            "stream parsing and artifact collection. Past API_MEMORY_LIMIT the "
            "kernel OOM-kills the API and every in-flight execution dies with it "
            "(#1552: 8 runs against what was then a 512m default). Default 4 "
            "was sized for that 512m; size it as (API_MEMORY_LIMIT_MiB - 128) / 96, e.g. "
            "20 for the 2g default, and check host RAM covers that many workspaces. "
            "Isolation is no longer the limit: concurrent executions once shared "
            "per-run processor state (#865), which is why this was 1; #1311 gave "
            "each execution its own state. Replaces "
            "SYN_POLLING_MAX_CONCURRENT_DISPATCHES, which is now ignored."
        ),
    )

    interrupt_budget_s: float = Field(
        default=DEFAULT_INTERRUPT_BUDGET_SECONDS,
        gt=0,
        description=(
            "Seconds a platform shutdown (deploy, restart, docker stop) waits for "
            "each running execution to save its unpushed commits to a quarantine "
            "ref and be recorded 'interrupted', which makes it resumable. Past it "
            "the execution is left running and the next start reconciles it as "
            "OrphanedByRestart. The api container's stop_grace_period must exceed "
            "this plus 95s of salvage settling plus uvicorn's graceful-shutdown "
            "timeout, or Docker kills the process first (#1381)."
        ),
    )

    run_queue_enabled: bool = Field(
        default=False,
        description=(
            "Admit executions into the Postgres run queue instead of running them "
            "in the admitting process (ADR-072, #1310 1.3). Off by default and NOT "
            "safe to turn on yet: nothing claims an admitted run until the "
            "ExecutionHost lands (#1310 1.5), so with this on every execution is "
            "admitted and never runs. Requires SYN_OBSERVABILITY_DB_URL; the API "
            "refuses to start an execution without it rather than queue in memory."
        ),
    )
