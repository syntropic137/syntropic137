"""Execution settings: how many workflow executions one API process runs (#1557).

See ADR-004 (settings) and ADR-060 (admission and dispatch limits).
"""

from __future__ import annotations

from enum import StrEnum

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


class ProcessRole(StrEnum):
    """Which half of the platform this process runs (ADR-072 D1, #1310 1.6).

    One image, two roles. ``api`` serves HTTP and owns the subscription, the
    pollers and, with the Run Queue off, every in-process execution. ``executor``
    only hosts the claim loop, so with the Run Queue off it runs idle. ``all`` is
    both, the single-process topology dev and tests keep.
    """

    API = "api"
    EXECUTOR = "executor"
    ALL = "all"

    @property
    def serves_api(self) -> bool:
        return self is not ProcessRole.EXECUTOR

    @property
    def hosts_executions(self) -> bool:
        return self is not ProcessRole.API


#: The fewest executions the API memory default is sized for, whatever the
#: budget: the north star's current tier (docs/north-star.md). It is the floor
#: under `api_memory_limit_for`. Without it the default concurrency of 4 would
#: derive 128 + 4 x 96 = 512MiB, the limit #1552 was OOM-killed at. With it, an
#: operator who raises SYN_EXECUTION_MAX_CONCURRENT up to this tier does not
#: also have to remember API_MEMORY_LIMIT.
API_MEMORY_FLOOR_EXECUTIONS = 20


def api_memory_limit_for(max_concurrent: int) -> str:
    """The API memory limit, in Docker notation, that holds `max_concurrent` executions.

    This is the inverse of `executions_that_fit`, using the same baseline and
    per-run allowance, and never sized below `API_MEMORY_FLOOR_EXECUTIONS`.
    It is written in whole gigabytes when it divides evenly, because that is
    how the compose fallback spells it.
    """
    executions = max(max_concurrent, API_MEMORY_FLOOR_EXECUTIONS)
    mib = API_BASELINE_MEMORY_MIB + executions * EXECUTION_API_MEMORY_MIB
    return f"{mib // 1024}g" if mib % 1024 == 0 else f"{mib}m"


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
            "The most workflow executions this process runs at once, across "
            "EVERY start path: POST /workflows/{id}/execute, trigger dispatch and "
            "resume. The budget actually applied is this or less: it is sized at "
            "startup from host cores, memory and free disk against the measured "
            "per-run demand (#1715), and /health reports it with the term that "
            "bound it. Further starts wait in a FIFO queue and show as status "
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

    # Sizing the budget from host capacity (#1715). The budget is
    # min(max_concurrent, cpu, memory, disk terms); see
    # syn_domain.contexts._shared.host_capacity for the formula.
    platform_reserve_cores: float = Field(
        default=2.0,
        ge=0,
        description=(
            "CPU cores kept back from executions for the platform itself (API, "
            "Postgres, event store, Redis) when the execution budget is sized from "
            "host capacity (#1715). The CPU term is (host cores - this) x "
            "SYN_EXECUTION_TARGET_UTILISATION / the measured median cores one run uses."
        ),
    )
    target_utilisation: float = Field(
        default=0.8,
        gt=0,
        le=1,
        description=(
            "Share of the CPU left after SYN_EXECUTION_PLATFORM_RESERVE_CORES that "
            "executions may use, between 0 and 1 (#1715). Headroom for bursts above "
            "the median."
        ),
    )
    memory_reserve_mb: int = Field(
        default=4096,
        ge=0,
        description=(
            "Host memory in MB kept back from executions for the platform (#1715). "
            "The memory term is (host memory - this) / the measured p95 peak memory "
            "of one run's workspace, never the SYN_WORKSPACE_MEMORY_LIMIT_MB cap."
        ),
    )
    disk_floor_gib: float = Field(
        default=10.0,
        ge=0,
        description=(
            "Free disk in GiB on the workspace volume kept back from executions "
            "(#1715). The disk term is (free disk - this) / the measured p95 disk "
            "one run's workspace leaves at teardown."
        ),
    )
    profile_window_days: float = Field(
        default=7.0,
        gt=0,
        description=(
            "How many days of phase resource profiles (#1716) the per-run demand is "
            "measured over when sizing the budget. With fewer than 10 measured "
            "phases in the window the budget is SYN_EXECUTION_MAX_CONCURRENT and "
            "/health says operator_max_no_profile."
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
            "in the admitting process (ADR-072, #1310 1.3). Off by default. With it "
            "on, this process registers an ExecutionHost (#1310 1.5) that claims "
            "admitted runs within SYN_EXECUTION_MAX_CONCURRENT, in the Executor Pool "
            "named by SYN_EXECUTOR_POOL_ID. Requires SYN_OBSERVABILITY_DB_URL; the API "
            "refuses to start an execution without it rather than queue in memory. "
            "On a compose install, also set COMPOSE_PROFILES=run-queue in .env: the "
            "executor service that claims runs is behind that profile and does not "
            "start without it (#1310 1.6)."
        ),
    )

    #: Read as SYN_EXECUTION_PROCESS_ROLE. ADR-072 spells it SYN_PROCESS_ROLE;
    #: the prefix is kept for the reason given at DEFAULT_INTERRUPT_BUDGET_SECONDS.
    process_role: ProcessRole = Field(
        default=ProcessRole.ALL,
        description=(
            "Which half of the platform this process runs (ADR-072 D1): 'api' "
            "serves HTTP, the subscription and the pollers; 'executor' only hosts "
            "the Run Queue claim loop, and is idle while "
            "SYN_EXECUTION_RUN_QUEUE_ENABLED is off; 'all' runs both in one "
            "process. Pinned per service by the compose files, not an operator knob."
        ),
    )


#: The slug every Executor Pool, provider and region name must match (ADR-072 D13).
POOL_SLUG_PATTERN = r"^[a-z][a-z0-9-]{0,62}$"


class ExecutorPoolSettings(BaseSettings):
    """The Executor Pool this process's ExecutionHost joins (ADR-072 D13).

    Only the operator facts nothing can derive. The provider and isolation level
    come from the workspace backend, never from here, so a declaration cannot
    disagree with what actually runs the workspaces. Read only with
    SYN_EXECUTION_RUN_QUEUE_ENABLED on.
    """

    model_config = SettingsConfigDict(
        env_prefix="SYN_EXECUTOR_POOL_",
        env_file=".env",
        extra="ignore",
        # .env.example writes unset values as empty; empty means the default.
        env_ignore_empty=True,
    )

    id: str = Field(
        default="default",
        pattern=POOL_SLUG_PATTERN,
        description=(
            "The Executor Pool this executor joins. Every executor naming one pool "
            "must declare the same priority, region, capabilities and overflow delay: "
            "a differing declaration is refused at startup while another member is "
            "live and not draining. To redefine a pool, drain its other members first."
        ),
    )
    priority: int = Field(
        default=0,
        ge=0,
        le=32767,
        description=(
            "The pool's priority; 0 is tried first. An executor claims only when no live "
            "executor in a higher-priority pool that could take the run has room or has "
            "been full for less than this pool's overflow delay; otherwise the run stays "
            "queued (ADR-072 D13)."
        ),
    )
    region: str | None = Field(
        default=None,
        pattern=POOL_SLUG_PATTERN,
        description="Where the pool's executors run, as a slug. Unset: no region stated.",
    )
    capabilities: tuple[str, ...] = Field(
        default=(),
        description=(
            'Features of this pool\'s hosts, as a JSON list, e.g. ["nested_docker"]. '
            "An unknown capability refuses startup."
        ),
    )
    overflow_delay_s: int = Field(
        default=60,
        ge=0,
        description=(
            "Seconds this pool's executors wait on a full higher-priority pool before "
            "overflowing past it (ADR-072 D13)."
        ),
    )
