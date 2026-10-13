"""Drive one token-free load test against a running stack (#1310 step 7c, #1717).

Admit N executions of the load-test workflow through the public API, paced
across the admission window, sample the stack until the sustain window has
passed and the runs have drained, and hand every observation to
``pass_bar.judge``. The driver decides nothing itself.

It reads only what any client could: ``GET /executions`` (the dashboard list),
``GET /executions/{id}`` (the dashboard detail) and ``GET /sessions/{id}``.
Container stats come from ``docker stats`` on the host the driver runs on;
where there is no docker CLI the stats check fails by name.

The stub is selected by the stack's workspace image, never by the driver, so
the driver proves it instead: every session read must report
``SCRIPTED_AGENT_MODEL``, and the first that does not stops the run.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

import httpx
from pydantic import BaseModel, ConfigDict

from syn_perf.loadtest.pass_bar import (
    TERMINAL_STATUSES,
    ContainerStat,
    LoadTestReport,
    PassBar,
    PhaseOutcome,
    RunOutcome,
    Sample,
    assert_scripted,
    judge,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from syn_perf.loadtest.scripted_agent_profile import ScriptedAgentProfile


@dataclass(frozen=True)
class Pacing:
    """How the run is admitted and watched. All of it comes from arguments."""

    admit_seconds: float
    """Spread the N starts evenly across this window."""
    sample_seconds: float
    drain_timeout_seconds: float
    """After the sustain window, how long to wait for every run to finish."""


@dataclass(frozen=True)
class Target:
    api_url: str
    workflow_id: str
    task: str
    containers: tuple[str, ...]
    """Platform containers to sample: API, Postgres, event store, socket proxy."""


# --- the slice of the API responses the driver reads -----------------------
# Declared here rather than imported from syn-api: syn-perf is a client of the
# HTTP contract, and ignoring extra fields keeps it a client of that contract
# rather than of the server's Python types.


class _Read(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")


class _Started(_Read):
    execution_id: str


class _Budget(_Read):
    running: int
    queued: int


class _Listed(_Read):
    workflow_execution_id: str


class _List(_Read):
    executions: list[_Listed]
    budget: _Budget | None = None


class _Phase(_Read):
    phase_id: str
    status: str
    session_id: str | None = None


class _Detail(_Read):
    workflow_execution_id: str
    status: str
    started_at: str | None = None
    phases: list[_Phase]


class _Operation(_Read):
    operation_type: str


class _Session(_Read):
    agent_model: str | None = None
    operations: list[_Operation]


async def run_load_test(
    target: Target,
    profile: ScriptedAgentProfile,
    bar: PassBar,
    pacing: Pacing,
) -> LoadTestReport:
    """Admit, sample, drain, then judge. Raises ``RealHarnessError`` on a real model."""
    async with httpx.AsyncClient(base_url=target.api_url, timeout=60.0) as client:
        ids = await _admit(client, target, bar.n, pacing.admit_seconds)
        samples: list[Sample] = []
        stats: list[ContainerStat] = []
        start = time.monotonic()
        deadline = start + pacing.admit_seconds + bar.sustain_seconds
        drain_deadline = deadline + pacing.drain_timeout_seconds
        proven: set[str] = set()
        while True:
            sample, details = await _sample(client, ids, time.monotonic() - start)
            samples.append(sample)
            await _prove_scripted(client, details, proven)
            stats.extend(await container_stats(target.containers))
            now = time.monotonic()
            drained = all(d is not None and d.status in TERMINAL_STATUSES for d in details)
            if now >= drain_deadline or (now >= deadline and drained):
                break
            await asyncio.sleep(pacing.sample_seconds)
        runs = await _outcomes(client, ids)
    return judge(bar, profile, samples, runs, stats, target.containers)


async def _admit(client: httpx.AsyncClient, target: Target, n: int, window: float) -> list[str]:
    """Start ``n`` executions from ``n`` concurrent clients, evenly over ``window``."""

    async def one(i: int) -> str:
        await asyncio.sleep(window * i / n)
        response = await client.post(
            f"/workflows/{target.workflow_id}/execute",
            json={"task": target.task, "tags": ["loadtest"], "no_eval": True},
        )
        response.raise_for_status()
        return _Started.model_validate_json(response.content).execution_id

    return list(await asyncio.gather(*(one(i) for i in range(n))))


async def _timed_get(client: httpx.AsyncClient, path: str) -> tuple[float, httpx.Response]:
    began = time.perf_counter()
    response = await client.get(path)
    return time.perf_counter() - began, response


async def _sample(
    client: httpx.AsyncClient, ids: Sequence[str], at: float
) -> tuple[Sample, list[_Detail | None]]:
    list_latency, listed = await _timed_get(client, "/executions?page_size=1")
    listed.raise_for_status()
    budget = _List.model_validate_json(listed.content).budget
    reads = await asyncio.gather(*(_timed_get(client, f"/executions/{i}") for i in ids))
    details = [
        _Detail.model_validate_json(r.content) if r.status_code == 200 else None for _, r in reads
    ]
    active = sum(p.status == "running" for d in details if d for p in d.phases)
    return (
        Sample(
            at_seconds=at,
            active_phases=active,
            budget_running=budget.running if budget else None,
            budget_queued=budget.queued if budget else None,
            list_latency_seconds=list_latency,
            detail_latency_seconds=tuple(t for t, _ in reads),
        ),
        details,
    )


async def _prove_scripted(
    client: httpx.AsyncClient, details: Sequence[_Detail | None], proven: set[str]
) -> None:
    """Stop at the first tick a session shows a real model, not after the run.

    A session joins ``proven`` once it has reported the scripted model; one
    that has reported no model yet is read again on the next tick.
    """
    for detail in details:
        if detail is None:
            continue
        for phase in detail.phases:
            if phase.session_id is None or phase.session_id in proven:
                continue
            outcome = await _phase_outcome(client, phase)
            assert_scripted(
                [RunOutcome(detail.workflow_execution_id, True, detail.status, None, (outcome,))]
            )
            if outcome.agent_model is not None:
                proven.add(phase.session_id)


async def _outcomes(client: httpx.AsyncClient, ids: Sequence[str]) -> list[RunOutcome]:
    runs: list[RunOutcome] = []
    for execution_id in ids:
        response = await client.get(f"/executions/{execution_id}")
        if response.status_code == 404:
            runs.append(RunOutcome(execution_id, False, None, None, ()))
            continue
        response.raise_for_status()
        detail = _Detail.model_validate_json(response.content)
        phases = tuple([await _phase_outcome(client, p) for p in detail.phases])
        run = RunOutcome(execution_id, True, detail.status, detail.started_at, phases)
        assert_scripted([run])
        runs.append(run)
    return runs


async def _phase_outcome(client: httpx.AsyncClient, phase: _Phase) -> PhaseOutcome:
    if phase.session_id is None:
        return PhaseOutcome(phase.phase_id, phase.status, None, None, None)
    response = await client.get(f"/sessions/{phase.session_id}")
    if response.status_code != 200:
        return PhaseOutcome(phase.phase_id, phase.status, phase.session_id, None, None)
    session = _Session.model_validate_json(response.content)
    started = sum(o.operation_type == "tool_execution_started" for o in session.operations)
    return PhaseOutcome(
        phase.phase_id, phase.status, phase.session_id, started, session.agent_model
    )


async def container_stats(containers: Sequence[str]) -> list[ContainerStat]:
    """One ``docker stats`` snapshot of ``containers``; empty without a docker CLI."""
    docker = shutil.which("docker")
    if not containers or docker is None:
        return []
    proc = await asyncio.create_subprocess_exec(
        docker,
        "stats",
        "--no-stream",
        "--format",
        "{{json .}}",
        *containers,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    out, _ = await proc.communicate()
    return [parse_docker_stats_line(line) for line in out.decode().splitlines() if line.strip()]


class _DockerStatsLine(_Read):
    Name: str
    CPUPerc: str
    MemUsage: str


_UNITS = {
    "B": 1,
    "KiB": 1024,
    "MiB": 1024**2,
    "GiB": 1024**3,
    "kB": 1000,
    "MB": 1000**2,
    "GB": 1000**3,
}


def parse_docker_stats_line(line: str) -> ContainerStat:
    """Parse one ``docker stats --format '{{json .}}'`` line."""
    row = _DockerStatsLine.model_validate(json.loads(line))
    used = row.MemUsage.split("/")[0].strip()
    unit = next(u for u in sorted(_UNITS, key=len, reverse=True) if used.endswith(u))
    return ContainerStat(
        container=row.Name,
        cpu_percent=float(row.CPUPerc.rstrip("%")),
        mem_bytes=int(float(used.removesuffix(unit)) * _UNITS[unit]),
    )
