"""Drive one token-free load test against a running stack (#1310 step 7c, #1717).

Admit N executions of the load-test workflow through the public API, paced
across the admission window while sampling the stack, keep sampling until
the sustain window has passed and the runs have drained, and hand every
observation to ``pass_bar.judge``, which makes every verdict. The driver
makes two observational decisions and states them where they are made: which
phases are active (``_sample``) and which timeline operations are tool starts
and ends (``TOOL_START_OPERATIONS``/``TOOL_END_OPERATIONS``).

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
from typing import TYPE_CHECKING, Final

import httpx
from pydantic import BaseModel, ConfigDict

from syn_perf.loadtest.pass_bar import (
    TERMINAL_STATUSES,
    TOOL_END_OPERATIONS,
    TOOL_START_OPERATIONS,
    Admission,
    ContainerRoles,
    ContainerStat,
    LoadTestReport,
    Observed,
    PassBar,
    PhaseOutcome,
    RealHarnessError,
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
    repos: tuple[str, ...]
    """Sent in every start's typed ``repos`` field: the workflow requires one (ADR-058)."""
    containers: ContainerRoles | None
    """Platform containers to sample: API, Postgres, event store, socket proxy."""


DASHBOARD_LIST_PAGE_SIZE: Final = 50
"""``EXECUTION_LIST_PAGE_SIZE`` in apps/syn-dashboard-ui/src/hooks/useListQuery.ts."""
LIST_READ_QUERY: Final = f"/executions?page=1&page_size={DASHBOARD_LIST_PAGE_SIZE}"
"""The request the dashboard's execution list makes (``listAllExecutions``)."""


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
    status: str
    started_at: str | None = None


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
    status: str = ""
    agent_model: str | None = None
    operations: list[_Operation]


async def run_load_test(
    target: Target,
    profile: ScriptedAgentProfile,
    bar: PassBar,
    pacing: Pacing,
) -> LoadTestReport:
    """Admit while sampling, drain, then judge.

    The clock starts before the first admission and sampling runs throughout
    it, so the report covers the initial load. A real model, or an API that
    fails a read, stops further admissions and the run, and the report is
    still written with everything observed up to then: an overloaded or
    misconfigured stack is exactly what this driver exists to report.
    """
    async with httpx.AsyncClient(base_url=target.api_url, timeout=60.0) as client:
        admitter = _Admitter(client, target, bar.n, pacing.admit_seconds)
        admitting = asyncio.create_task(admitter.run())
        watched = _Watch(samples=[], stats=[])
        try:
            await _watch(client, target, bar, pacing, admitter, admitting, watched)
        except RealHarnessError as exc:
            watched.refused = f"real harness: {exc}"
        except httpx.HTTPError as exc:
            watched.refused = f"the API at {target.api_url} failed a read: {exc!r}"
        if watched.refused is not None:
            admitting.cancel()
        await asyncio.gather(admitting, return_exceptions=True)
        try:
            runs = await _outcomes(client, admitter.ids)
        except httpx.HTTPError as exc:
            # The admitted ids are still in the report; their end state is not.
            runs = []
            watched.refused = (
                watched.refused or f"the API at {target.api_url} failed the final reads: {exc!r}"
            )
    observed = Observed(
        admission=admitter.result(),
        samples=watched.samples,
        runs=runs,
        containers=watched.stats,
        list_read_query=LIST_READ_QUERY,
        refused=watched.refused,
    )
    return judge(bar, profile, observed, target.containers)


def start_body(target: Target) -> dict[str, object]:
    """The ``POST /workflows/{id}/execute`` body for one load-test start."""
    return {
        "task": target.task,
        "repos": list(target.repos),
        "tags": ["loadtest"],
        "no_eval": True,
    }


@dataclass
class _Watch:
    """What sampling has seen so far; kept when sampling is cut short."""

    samples: list[Sample]
    stats: list[ContainerStat]
    refused: str | None = None


async def _watch(
    client: httpx.AsyncClient,
    target: Target,
    bar: PassBar,
    pacing: Pacing,
    admitter: _Admitter,
    admitting: asyncio.Task[None],
    watched: _Watch,
) -> None:
    """Sample from the first admission until sustained and drained, or the drain deadline."""
    start = time.monotonic()
    deadline = start + pacing.admit_seconds + bar.sustain_seconds
    drain_deadline = deadline + pacing.drain_timeout_seconds
    while True:
        sample, details = await _sample(client, admitter.ids, time.monotonic() - start)
        watched.samples.append(sample)
        watched.stats.extend(await container_stats(target.containers))
        now = time.monotonic()
        drained = all(d is not None and d.status in TERMINAL_STATUSES for d in details)
        # Admission ends on its own (window plus one request timeout), and
        # the run is not over while starts are still being sent.
        if admitting.done() and (now >= drain_deadline or (now >= deadline and drained)):
            return
        await asyncio.sleep(pacing.sample_seconds)


class _Admitter:
    """Starts ``n`` executions evenly over ``window`` and keeps every outcome.

    One refused start does not abandon the others or the ids already admitted:
    each attempt is recorded, and the ids are readable while admission runs.
    """

    def __init__(self, client: httpx.AsyncClient, target: Target, n: int, window: float) -> None:
        self._client = client
        self._target = target
        self._n = n
        self._window = window
        self.ids: list[str] = []
        self._rejected: list[str] = []
        self._first_sent: float | None = None
        self._last_answered: float | None = None

    async def run(self) -> None:
        await asyncio.gather(*(self._one(i) for i in range(self._n)))

    async def _one(self, i: int) -> None:
        await asyncio.sleep(self._window * i / self._n)
        sent = time.monotonic()
        self._first_sent = sent if self._first_sent is None else min(self._first_sent, sent)
        try:
            response = await self._client.post(
                f"/workflows/{self._target.workflow_id}/execute", json=start_body(self._target)
            )
            response.raise_for_status()
            self.ids.append(_Started.model_validate_json(response.content).execution_id)
        except httpx.HTTPStatusError as exc:
            self._rejected.append(f"start {i}: HTTP {exc.response.status_code} {exc.response.text}")
        except httpx.HTTPError as exc:
            self._rejected.append(f"start {i}: {exc!r}")
        finally:
            self._last_answered = time.monotonic()

    def result(self) -> Admission:
        elapsed = (
            None
            if self._first_sent is None or self._last_answered is None
            else self._last_answered - self._first_sent
        )
        unsent = self._n - len(self.ids) - len(self._rejected)
        rejected = [*self._rejected, *([f"{unsent} starts never sent"] if unsent else [])]
        return Admission(tuple(self.ids), tuple(rejected), elapsed)


async def _timed_get(client: httpx.AsyncClient, path: str) -> tuple[float, httpx.Response]:
    began = time.perf_counter()
    response = await client.get(path)
    return time.perf_counter() - began, response


async def _sample(
    client: httpx.AsyncClient, ids: Sequence[str], at: float
) -> tuple[Sample, list[_Detail | None]]:
    """One tick: the list read, every detail read, and the session of every running phase.

    A phase is ``running`` from ``PhaseStarted``, before its workspace is
    provisioned, so it counts as active only when its agent session is
    ``running`` too. The same session read proves the model is the scripted
    one, so a real harness stops the run on the tick it is first seen.
    """
    list_latency, listed = await _timed_get(client, LIST_READ_QUERY)
    listed.raise_for_status()
    budget = _List.model_validate_json(listed.content).budget
    reads = await asyncio.gather(*(_timed_get(client, f"/executions/{i}") for i in ids))
    details = [
        _Detail.model_validate_json(r.content) if r.status_code == 200 else None for _, r in reads
    ]
    running = [
        (d.workflow_execution_id, p)
        for d in details
        if d
        for p in d.phases
        if p.status == "running" and p.session_id is not None
    ]
    sessions = await asyncio.gather(*(_session(client, p.session_id) for _, p in running))
    assert_scripted(
        [
            RunOutcome(
                eid,
                True,
                None,
                None,
                (PhaseOutcome(p.phase_id, p.status, p.session_id, None, None, s.agent_model),),
            )
            for (eid, p), s in zip(running, sessions, strict=True)
            if s is not None
        ]
    )
    active = sum(s is not None and s.status == "running" for s in sessions)
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


async def _session(client: httpx.AsyncClient, session_id: str | None) -> _Session | None:
    if session_id is None:
        return None
    response = await client.get(f"/sessions/{session_id}")
    return _Session.model_validate_json(response.content) if response.status_code == 200 else None


async def _outcomes(client: httpx.AsyncClient, ids: Sequence[str]) -> list[RunOutcome]:
    """Each submitted execution as the dashboard list and detail describe it.

    Found, status and ``started_at`` come from the list, because that read
    model is where a dropped start shows: the #598 fallback creates a row with
    no ``started_at`` for a failure whose start was never applied (#1545,
    #1550). An execution the list never shows is lost. Phases come from detail.
    """
    runs: list[RunOutcome] = []
    for execution_id in ids:
        listed = await client.get("/executions", params={"q": execution_id, "page_size": 5})
        listed.raise_for_status()
        row = next(
            (
                e
                for e in _List.model_validate_json(listed.content).executions
                if e.workflow_execution_id == execution_id
            ),
            None,
        )
        if row is None:
            runs.append(RunOutcome(execution_id, False, None, None, ()))
            continue
        response = await client.get(f"/executions/{execution_id}")
        response.raise_for_status()
        detail = _Detail.model_validate_json(response.content)
        phases = tuple([await _phase_outcome(client, p) for p in detail.phases])
        runs.append(RunOutcome(execution_id, True, row.status, row.started_at, phases))
    return runs


async def _phase_outcome(client: httpx.AsyncClient, phase: _Phase) -> PhaseOutcome:
    session = await _session(client, phase.session_id)
    if session is None:
        return PhaseOutcome(phase.phase_id, phase.status, phase.session_id, None, None, None)
    types = [o.operation_type for o in session.operations]
    return PhaseOutcome(
        phase.phase_id,
        phase.status,
        phase.session_id,
        sum(t in TOOL_START_OPERATIONS for t in types),
        sum(t in TOOL_END_OPERATIONS for t in types),
        session.agent_model,
    )


async def container_stats(roles: ContainerRoles | None) -> list[ContainerStat]:
    """One ``docker stats`` snapshot of every role; empty without a docker CLI or roles."""
    docker = shutil.which("docker")
    if roles is None or docker is None:
        return []
    containers = roles.by_role().values()
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
