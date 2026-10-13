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

if TYPE_CHECKING:
    from collections.abc import Sequence

    from syn_perf.loadtest.scripted_agent_profile import ScriptedAgentProfile

TERMINAL_STATUSES: Final = frozenset({"completed", "failed", "cancelled", "interrupted"})
NOT_YET_STARTED: Final = frozenset({"pending", "queued", "not_started"})


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
    tool_operations: int | None
    """``tool_execution_started`` operations stored for the session; ``None``
    when the session could not be read."""
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
class PassBar:
    """What the run is held to. Every figure is an argument, none is a constant."""

    n: int
    sustain_seconds: float
    read_p95_seconds: float


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
    peak_active_phases: int
    seconds_at_n: float
    list_p95_seconds: float | None
    detail_p95_seconds: float | None
    lost: list[str]
    orphaned: list[str]
    dropped_starts: list[str]
    event_count_mismatches: list[str]
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


def judge(
    bar: PassBar,
    profile: ScriptedAgentProfile,
    samples: Sequence[Sample],
    runs: Sequence[RunOutcome],
    containers: Sequence[ContainerStat],
    expected_containers: Sequence[str],
) -> LoadTestReport:
    """Hold one run's observations to ``bar``."""
    assert_scripted(runs)
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
    peaks = _container_peaks(containers)
    missing_containers = sorted(set(expected_containers) - {c.container for c in peaks})

    checks = [
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
            detail=f"{len(mismatches)} completed phases off their scripted tool-use count",
        ),
        Check(
            name="container_stats",
            passed=not missing_containers,
            detail=(
                f"no stats for {missing_containers}"
                if missing_containers
                else f"sampled {len(peaks)} containers"
            ),
        ),
    ]
    return LoadTestReport(
        n=bar.n,
        tier=profile.tier,
        peak_active_phases=peak,
        seconds_at_n=at_n,
        list_p95_seconds=list_p95,
        detail_p95_seconds=detail_p95,
        lost=lost,
        orphaned=orphaned,
        dropped_starts=dropped,
        event_count_mismatches=mismatches,
        containers=peaks,
        samples=list(samples),
        checks=checks,
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
    """Completed phases whose stored tool operations differ from the recording's count."""
    off: list[str] = []
    for run in runs:
        for phase in run.phases:
            if phase.status != "completed":
                continue
            expected = profile.phases[phase.phase_id].stream.tool_uses
            if phase.tool_operations != expected:
                off.append(
                    f"{run.execution_id}/{phase.phase_id}: stored {phase.tool_operations}, "
                    f"scripted {expected}"
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
