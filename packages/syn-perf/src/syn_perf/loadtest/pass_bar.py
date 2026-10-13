"""The north-star pass bar for one load-test run, judged from server reads (#1717).

Everything here is pure: the driver observes the stack and hands the
observations in, and this module decides. That keeps every verdict testable
against synthetic observations, including the ones that must fail (a peak
below N, one dropped observation in fifty, a real model in a session).

Two rules shape it (docs/north-star.md):

- **Concurrent means a phase actively running, counted by the server.** A
  dispatched execution, a queued phase, a phase still provisioning or an idle
  slot does not count, so ``Sample.active_phases`` is read off phase and
  session status on the server, never off what the driver submitted. A run whose peak stays below N is reported as
  a queue test with its measured peak, and fails.
- **Unknown is not a pass.** A measurement the driver could not take (no
  container stats, a session it could not read) fails its check by name
  rather than being left out of the report.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from pydantic import BaseModel, ConfigDict

from syn_perf.loadtest.scripted_agent_profile import SCRIPTED_AGENT_MODEL
from syn_shared.events import (
    SUBAGENT_STARTED,
    SUBAGENT_STOPPED,
    TOOL_EXECUTION_COMPLETED,
    TOOL_EXECUTION_STARTED,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from syn_perf.loadtest.scripted_agent_profile import ScriptedAgentProfile

TERMINAL_STATUSES: Final = frozenset({"completed", "failed", "cancelled", "interrupted"})
NOT_YET_STARTED: Final = frozenset({"pending", "queued", "not_started"})

# The session timeline relabels an Agent/Task tool event as a subagent
# operation (session_tools_dispatch.to_operation), so one recorded tool use is
# EITHER a tool start OR a subagent start there, never both and never neither.
TOOL_START_OPERATIONS: Final = frozenset({TOOL_EXECUTION_STARTED, SUBAGENT_STARTED})
TOOL_END_OPERATIONS: Final = frozenset({TOOL_EXECUTION_COMPLETED, SUBAGENT_STOPPED})

# docs/north-star.md: dashboard reads under 500 ms, N admitted within five
# minutes, held for thirty. A run held to anything looser is an experiment,
# and the report says so rather than certifying it.
NORTH_STAR_READ_P95_SECONDS: Final = 0.5
NORTH_STAR_ADMIT_SECONDS: Final = 300.0
NORTH_STAR_SUSTAIN_SECONDS: Final = 1800.0


class RealHarnessError(RuntimeError):
    """A session reported a model other than the scripted one: tokens were spent."""


@dataclass(frozen=True)
class Sample:
    """One sampling tick, every figure as the server reported it."""

    at_seconds: float
    """Seconds since the first admission."""
    active_phases: int
    """Phases of this run's executions that are ``running`` with their agent
    session ``running`` too; a phase still provisioning does not count."""
    budget_running: int | None
    budget_queued: int | None
    list_latency_seconds: float
    detail_latency_seconds: tuple[float, ...]


@dataclass(frozen=True)
class PhaseOutcome:
    phase_id: str
    status: str
    session_id: str | None
    tool_starts: int | None
    """Tool and subagent starts stored for the session; ``None`` when the
    session could not be read."""
    tool_ends: int | None
    """Tool and subagent completions stored for the session; ``None`` likewise."""
    agent_model: str | None


@dataclass(frozen=True)
class RunOutcome:
    """An execution the driver submitted, as the server describes it at the end."""

    execution_id: str
    found: bool
    status: str | None
    started_at: str | None
    phases: tuple[PhaseOutcome, ...]


@dataclass(frozen=True)
class ContainerStat:
    container: str
    cpu_percent: float
    mem_bytes: int


@dataclass(frozen=True)
class ContainerRoles:
    """The platform containers the north star names, by role. Names vary by stack."""

    api: str
    postgres: str
    event_store: str
    socket_proxy: str

    def by_role(self) -> dict[str, str]:
        return {
            "api": self.api,
            "postgres": self.postgres,
            "event_store": self.event_store,
            "socket_proxy": self.socket_proxy,
        }


@dataclass(frozen=True)
class Admission:
    """What admitting the run actually took, as the driver measured it."""

    admitted: tuple[str, ...]
    """Execution ids the API accepted, in admission order."""
    rejected: tuple[str, ...]
    """One line per start the API refused or never answered."""
    elapsed_seconds: float | None
    """First POST sent to last POST answered; ``None`` when nothing was sent."""


@dataclass(frozen=True)
class PassBar:
    """What the run is held to. Every figure is an argument, none is a constant."""

    n: int
    sustain_seconds: float
    read_p95_seconds: float
    admit_seconds: float = NORTH_STAR_ADMIT_SECONDS

    @property
    def is_north_star(self) -> bool:
        return (
            self.read_p95_seconds <= NORTH_STAR_READ_P95_SECONDS
            and self.admit_seconds <= NORTH_STAR_ADMIT_SECONDS
            and self.sustain_seconds >= NORTH_STAR_SUSTAIN_SECONDS
        )


class Check(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    passed: bool
    detail: str


class ContainerPeak(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    container: str
    samples: int
    cpu_percent_p95: float
    mem_bytes_peak: int


class LoadTestReport(BaseModel):
    """The report ``syn_perf.loadtest`` writes; ``passed`` is the exit status."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    n: int
    tier: str
    list_read_query: str
    """The dashboard list request each tick timed, so the p95 says what it is of."""
    refused: str | None
    """Why the run stopped early, or ``None``; a refused run still reports."""
    admitted: list[str]
    admission_rejected: list[str]
    admission_seconds: float | None
    peak_active_phases: int
    seconds_at_n: float
    list_p95_seconds: float | None
    detail_p95_seconds: float | None
    lost: list[str]
    orphaned: list[str]
    dropped_starts: list[str]
    event_count_mismatches: list[str]
    unscripted_sessions: list[str]
    containers: list[ContainerPeak]
    samples: list[Sample]
    checks: list[Check]

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks)


def p95(values: Sequence[float]) -> float | None:
    """Nearest-rank 95th percentile; ``None`` for no values."""
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(math.ceil(0.95 * len(ordered)) - 1, 0)]


def assert_scripted(runs: Sequence[RunOutcome]) -> None:
    """Raise if any session observed a model other than the scripted agent's.

    A session with no model yet is not proof either way and is left to the
    next read; one with any other model is a real harness, and the run stops.
    """
    real = sorted(
        f"{r.execution_id}/{p.phase_id}={p.agent_model}"
        for r in runs
        for p in r.phases
        if p.agent_model is not None and p.agent_model != SCRIPTED_AGENT_MODEL
    )
    if real:
        msg = (
            f"sessions reported a real model, so a real harness ran and spent tokens: {real}. "
            f"The stack's workspace image must be the stub, which reports {SCRIPTED_AGENT_MODEL!r}"
        )
        raise RealHarnessError(msg)


def _unscripted(runs: Sequence[RunOutcome]) -> list[str]:
    """Sessions that did not positively report the scripted model by the end.

    During the run an absent model is not yet evidence; at the end it is the
    absence of the proof the run depends on, so it fails like a real one.
    """
    return sorted(
        f"{r.execution_id}/{p.phase_id}={p.agent_model}"
        for r in runs
        for p in r.phases
        if p.agent_model != SCRIPTED_AGENT_MODEL
    )


@dataclass(frozen=True)
class Observed:
    """Everything one run observed, refused or not."""

    admission: Admission
    samples: Sequence[Sample]
    runs: Sequence[RunOutcome]
    containers: Sequence[ContainerStat]
    list_read_query: str
    refused: str | None = None


def judge(
    bar: PassBar,
    profile: ScriptedAgentProfile,
    observed: Observed,
    roles: ContainerRoles | None,
) -> LoadTestReport:
    """Hold one run's observations to ``bar``. Never raises on what it observed."""
    samples, runs, containers = observed.samples, observed.runs, observed.containers
    admission = observed.admission
    peak = max((s.active_phases for s in samples), default=0)
    at_n = _seconds_at_or_above(samples, bar.n)
    list_p95 = p95([s.list_latency_seconds for s in samples])
    detail_p95 = p95([d for s in samples for d in s.detail_latency_seconds])
    lost = sorted(r.execution_id for r in runs if not r.found)
    orphaned = sorted(r.execution_id for r in runs if r.found and r.status not in TERMINAL_STATUSES)
    dropped = sorted(
        r.execution_id
        for r in runs
        if r.found and r.status not in NOT_YET_STARTED and r.started_at is None
    )
    mismatches = _event_count_mismatches(profile, runs)
    unscripted = _unscripted(runs)
    peaks = _container_peaks(containers)

    checks = [
        _north_star_check(bar),
        Check(
            name="refused",
            passed=observed.refused is None,
            detail=observed.refused or "the run was not stopped early",
        ),
        _admission_check(bar, admission),
        Check(
            name="scripted",
            passed=not unscripted,
            detail=f"{len(unscripted)} sessions without the scripted model {SCRIPTED_AGENT_MODEL!r}",
        ),
        Check(
            name="concurrency",
            passed=peak >= bar.n and at_n >= bar.sustain_seconds,
            detail=(
                f"{bar.n} phases active for {at_n:.0f}s of the {bar.sustain_seconds:.0f}s required"
                if peak >= bar.n
                else f"queue test, not {bar.n} concurrent: peak {peak} active phases"
            ),
        ),
        _latency_check("list_read_p95", list_p95, bar.read_p95_seconds),
        _latency_check("detail_read_p95", detail_p95, bar.read_p95_seconds),
        Check(name="lost", passed=not lost, detail=f"{len(lost)} submitted, never listed"),
        Check(
            name="orphaned",
            passed=not orphaned,
            detail=f"{len(orphaned)} not terminal when the run ended",
        ),
        Check(
            name="dropped_starts",
            passed=not dropped,
            detail=f"{len(dropped)} past pending with no started_at (#1550)",
        ),
        Check(
            name="event_counts",
            passed=not mismatches,
            detail=f"{len(mismatches)} planned phases off their scripted tool-use count",
        ),
        _container_check(roles, peaks),
    ]
    return LoadTestReport(
        n=bar.n,
        tier=profile.tier,
        list_read_query=observed.list_read_query,
        refused=observed.refused,
        admitted=list(admission.admitted),
        admission_rejected=list(admission.rejected),
        admission_seconds=admission.elapsed_seconds,
        peak_active_phases=peak,
        seconds_at_n=at_n,
        list_p95_seconds=list_p95,
        detail_p95_seconds=detail_p95,
        lost=lost,
        orphaned=orphaned,
        dropped_starts=dropped,
        event_count_mismatches=mismatches,
        unscripted_sessions=unscripted,
        containers=peaks,
        samples=list(samples),
        checks=checks,
    )


def _north_star_check(bar: PassBar) -> Check:
    return Check(
        name="north_star_bar",
        passed=bar.is_north_star,
        detail=(
            f"held to read p95 {bar.read_p95_seconds:.3f}s, admit {bar.admit_seconds:.0f}s, "
            f"sustain {bar.sustain_seconds:.0f}s; the north star is "
            f"<{NORTH_STAR_READ_P95_SECONDS}s, <={NORTH_STAR_ADMIT_SECONDS:.0f}s, "
            f">={NORTH_STAR_SUSTAIN_SECONDS:.0f}s"
        ),
    )


def _admission_check(bar: PassBar, admission: Admission) -> Check:
    """All N admitted, and the last answered within ``bar.admit_seconds`` of the first sent."""
    elapsed = admission.elapsed_seconds
    return Check(
        name="admission",
        passed=len(admission.admitted) == bar.n
        and elapsed is not None
        and elapsed <= bar.admit_seconds,
        detail=(
            f"{len(admission.admitted)}/{bar.n} admitted in "
            f"{'n/a' if elapsed is None else f'{elapsed:.1f}'}s "
            f"(limit {bar.admit_seconds:.0f}s); rejected {list(admission.rejected)}"
        ),
    )


def _container_check(roles: ContainerRoles | None, peaks: Sequence[ContainerPeak]) -> Check:
    """Every north-star role sampled at least once; no roles at all misses all four."""
    sampled = {c.container for c in peaks}
    missing = (
        ["api", "postgres", "event_store", "socket_proxy"]
        if roles is None
        else sorted(role for role, name in roles.by_role().items() if name not in sampled)
    )
    return Check(
        name="container_stats",
        passed=not missing,
        detail=f"no stats for roles {missing}" if missing else f"sampled {len(peaks)} containers",
    )


def _seconds_at_or_above(samples: Sequence[Sample], n: int) -> float:
    """The longest unbroken stretch, in seconds, with at least ``n`` phases active."""
    best = 0.0
    since: float | None = None
    for sample in samples:
        if sample.active_phases >= n:
            since = sample.at_seconds if since is None else since
            best = max(best, sample.at_seconds - since)
        else:
            since = None
    return best


def _latency_check(name: str, value: float | None, limit: float) -> Check:
    if value is None:
        return Check(name=name, passed=False, detail="no reads were timed")
    return Check(name=name, passed=value < limit, detail=f"p95 {value:.3f}s, limit {limit:.3f}s")


def _event_count_mismatches(profile: ScriptedAgentProfile, runs: Sequence[RunOutcome]) -> list[str]:
    """Planned phases whose stored tool starts or ends differ from the recording.

    Every phase the profile plans must be present and completed, and must hold
    exactly the scripted number of starts AND of ends: a missing phase, a
    failed one, an unreadable session or a dropped completion is a mismatch.
    A run that never appeared in the list is reported as lost instead.
    """
    planned = profile.planned_run().ran
    off: list[str] = []
    for run in runs:
        if not run.found:
            continue
        seen = {p.phase_id: p for p in run.phases}
        for phase_id in planned:
            expected = profile.phases[phase_id].stream.tool_uses
            phase = seen.get(phase_id)
            if phase is None:
                off.append(f"{run.execution_id}/{phase_id}: phase missing")
            elif phase.status != "completed":
                off.append(f"{run.execution_id}/{phase_id}: {phase.status}, not completed")
            elif phase.tool_starts != expected or phase.tool_ends != expected:
                off.append(
                    f"{run.execution_id}/{phase_id}: stored {phase.tool_starts} starts and "
                    f"{phase.tool_ends} ends, scripted {expected}"
                )
    return sorted(off)


def _container_peaks(stats: Sequence[ContainerStat]) -> list[ContainerPeak]:
    by_name: dict[str, list[ContainerStat]] = {}
    for stat in stats:
        by_name.setdefault(stat.container, []).append(stat)
    return [
        ContainerPeak(
            container=name,
            samples=len(seen),
            cpu_percent_p95=p95([s.cpu_percent for s in seen]) or 0.0,
            mem_bytes_peak=max(s.mem_bytes for s in seen),
        )
        for name, seen in sorted(by_name.items())
    ]
