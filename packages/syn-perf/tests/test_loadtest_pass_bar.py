"""The load-test pass bar fails the runs it must fail (#1717, #1310 section 6.5)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest

from syn_domain.contexts.orchestration import WorkflowDefinition
from syn_perf.loadtest import driver
from syn_perf.loadtest.driver import Pacing, Target, parse_docker_stats_line, run_load_test
from syn_perf.loadtest.pass_bar import (
    ContainerStat,
    PassBar,
    PhaseOutcome,
    RealHarnessError,
    RunOutcome,
    Sample,
    judge,
    p95,
)
from syn_perf.loadtest.scripted_agent_profile import (
    SCRIPTED_AGENT_MODEL,
    NoWorkload,
    ScriptedAgentProfile,
    ScriptedStream,
)

pytestmark = pytest.mark.unit

_WORKFLOW = Path(__file__).resolve().parents[3] / "workflows/sdlc/implement-v3/workflow.yaml"
_TOOL_USES = 50
_CONTAINERS = ("syn-api", "syn-db", "syn-event-store", "syn-socket-proxy")


@pytest.fixture(scope="module")
def profile() -> ScriptedAgentProfile:
    workflow = WorkflowDefinition.from_file(_WORKFLOW)
    return ScriptedAgentProfile.for_workflow(
        workflow,
        tier="platform",
        fixture_repo="syntropic137/loadtest-fixture",
        streams={
            p.id: ScriptedStream(
                harness=(p.agent.provider if p.agent else None) or "claude",
                recording=f"/recordings/{p.id}.jsonl",
                cli_version="1",
                tool_uses=_TOOL_USES,
            )
            for p in workflow.phases
        },
        workload=NoWorkload(),
    )


def _run(
    profile: ScriptedAgentProfile,
    i: int,
    *,
    stored: int = _TOOL_USES,
    model: str = SCRIPTED_AGENT_MODEL,
    status: str = "completed",
    started_at: str | None = "2026-10-13T08:00:00Z",
) -> RunOutcome:
    phases = tuple(
        PhaseOutcome(p, "completed", f"s-{i}-{p}", stored, model) for p in profile.planned_run().ran
    )
    return RunOutcome(f"exec-{i}", True, status, started_at, phases)


def _samples(active: list[int], every: float = 60.0) -> list[Sample]:
    return [Sample(k * every, a, a, 0, 0.1, (0.2,)) for k, a in enumerate(active)]


def _stats() -> list[ContainerStat]:
    return [ContainerStat(c, 10.0, 100) for c in _CONTAINERS]


def _judge(profile: ScriptedAgentProfile, samples: list[Sample], runs: list[RunOutcome]):
    bar = PassBar(n=4, sustain_seconds=120.0, read_p95_seconds=2.0)
    return judge(bar, profile, samples, runs, _stats(), _CONTAINERS)


def _failed(report) -> set[str]:
    return {c.name for c in report.checks if not c.passed}


def test_a_clean_run_at_n_passes(profile: ScriptedAgentProfile) -> None:
    report = _judge(profile, _samples([4, 4, 4, 4]), [_run(profile, i) for i in range(4)])
    assert report.passed, report.checks
    assert report.seconds_at_n == 180.0


def test_a_peak_below_n_is_a_queue_test_and_fails(profile: ScriptedAgentProfile) -> None:
    report = _judge(profile, _samples([3, 3, 3, 3]), [_run(profile, i) for i in range(4)])
    assert _failed(report) == {"concurrency"}
    assert "queue test" in report.checks[0].detail
    assert "peak 3" in report.checks[0].detail


def test_n_reached_too_briefly_fails(profile: ScriptedAgentProfile) -> None:
    report = _judge(profile, _samples([4, 4, 3, 4, 4]), [_run(profile, i) for i in range(4)])
    assert _failed(report) == {"concurrency"}


def test_one_dropped_observation_in_fifty_fails(profile: ScriptedAgentProfile) -> None:
    runs = [_run(profile, 0, stored=_TOOL_USES - 1), *(_run(profile, i) for i in (1, 2, 3))]
    report = _judge(profile, _samples([4, 4, 4]), runs)
    assert _failed(report) == {"event_counts"}
    assert len(report.event_count_mismatches) == len(profile.planned_run().ran)


def test_an_unreadable_session_is_not_a_match(profile: ScriptedAgentProfile) -> None:
    runs = [_run(profile, 0), _run(profile, 1)]
    unread = RunOutcome(
        "exec-9", True, "completed", "t", (PhaseOutcome("premise", "completed", "s", None, None),)
    )
    report = _judge(profile, _samples([4, 4, 4]), [*runs, unread])
    assert "event_counts" in _failed(report)


def test_a_real_model_stops_the_run(profile: ScriptedAgentProfile) -> None:
    with pytest.raises(RealHarnessError, match="claude-sonnet"):
        _judge(profile, _samples([4]), [_run(profile, 0, model="claude-sonnet-5-5")])


def test_lost_orphaned_and_dropped_starts_are_counted(profile: ScriptedAgentProfile) -> None:
    runs = [
        _run(profile, 0),
        RunOutcome("exec-lost", False, None, None, ()),
        _run(profile, 2, status="running"),
        _run(profile, 3, started_at=None),
    ]
    report = _judge(profile, _samples([4, 4, 4]), runs)
    assert report.lost == ["exec-lost"]
    assert report.orphaned == ["exec-2"]
    assert report.dropped_starts == ["exec-3"]
    assert {"lost", "orphaned", "dropped_starts"} <= _failed(report)


def test_slow_reads_and_missing_container_stats_fail(profile: ScriptedAgentProfile) -> None:
    slow = [Sample(k * 60.0, 4, 4, 0, 3.0, (2.5,)) for k in range(4)]
    bar = PassBar(n=4, sustain_seconds=120.0, read_p95_seconds=2.0)
    report = judge(bar, profile, slow, [_run(profile, 0)], [], _CONTAINERS)
    assert {"list_read_p95", "detail_read_p95", "container_stats"} <= _failed(report)


def test_p95_is_nearest_rank() -> None:
    assert p95([float(v) for v in range(1, 101)]) == 95.0
    assert p95([]) is None


def test_docker_stats_line_parses() -> None:
    line = json.dumps({"Name": "syn-db", "CPUPerc": "12.50%", "MemUsage": "1.5GiB / 2GiB"})
    assert parse_docker_stats_line(line) == ContainerStat("syn-db", 12.5, 1610612736)


# --- the driver against a stand-in API --------------------------------------


async def test_driver_counts_active_phases_from_the_server(
    profile: ScriptedAgentProfile, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two executions are admitted but only one phase is ever ``running``.

    A driver that counted what it dispatched would report 2; the server says 1.
    """
    started: list[str] = []
    ran = profile.planned_run().ran

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "POST":
            started.append(f"exec-{len(started)}")
            return httpx.Response(200, json={"execution_id": started[-1], "workflow_id": "w"})
        if path == "/executions":
            # exec-1 lost its start: the list row has no started_at (#1550).
            q = request.url.params.get("q")
            rows = [
                {"workflow_execution_id": q, "status": "completed", "started_at": None}
                if q == "exec-1"
                else {"workflow_execution_id": q, "status": "completed", "started_at": "t"}
            ]
            return httpx.Response(200, json={"executions": rows if q else [], "total": 1})
        if path.startswith("/executions/"):
            eid = path.rsplit("/", 1)[1]
            first = eid == "exec-0"
            phases = [
                {
                    "phase_id": p,
                    "status": "running" if first and k == 0 else "completed",
                    "session_id": f"{eid}-{p}",
                }
                for k, p in enumerate(ran)
            ]
            return httpx.Response(
                200,
                json={
                    "workflow_execution_id": eid,
                    "status": "completed",
                    "started_at": "t",
                    "phases": phases,
                },
            )
        ops = [{"operation_type": "tool_execution_started"}] * _TOOL_USES
        # Every session says running; only exec-0's first phase is running too.
        return httpx.Response(
            200,
            json={"agent_model": SCRIPTED_AGENT_MODEL, "status": "running", "operations": ops},
        )

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        driver.httpx,
        "AsyncClient",
        lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw),
    )
    report = await run_load_test(
        Target("http://stack", "sdlc-implement-v3", "t", ()),
        profile,
        PassBar(n=2, sustain_seconds=0.0, read_p95_seconds=2.0),
        Pacing(admit_seconds=0.0, sample_seconds=0.1, drain_timeout_seconds=0.0),
    )
    assert started == ["exec-0", "exec-1"]
    assert report.peak_active_phases == 1
    assert "concurrency" in _failed(report)
    assert report.event_count_mismatches == []
    assert report.dropped_starts == ["exec-1"]
    assert report.lost == []


async def test_driver_stops_at_the_first_real_model(
    profile: ScriptedAgentProfile, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A real harness stops the run on the tick it is seen, not after an hour's sustain."""
    reads: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "POST":
            return httpx.Response(200, json={"execution_id": "exec-0", "workflow_id": "w"})
        if path == "/executions":
            return httpx.Response(200, json={"executions": [], "total": 0})
        if path.startswith("/executions/"):
            phase = {"phase_id": "premise", "status": "running", "session_id": "s-0"}
            body = {"workflow_execution_id": "exec-0", "status": "running", "phases": [phase]}
            return httpx.Response(200, json=body)
        reads.append(path)
        return httpx.Response(200, json={"agent_model": "claude-opus-5-5", "operations": []})

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        driver.httpx,
        "AsyncClient",
        lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw),
    )
    with pytest.raises(RealHarnessError, match="claude-opus-5-5"):
        await asyncio.wait_for(
            run_load_test(
                Target("http://stack", "sdlc-implement-v3", "t", ()),
                profile,
                PassBar(n=1, sustain_seconds=3600.0, read_p95_seconds=2.0),
                Pacing(admit_seconds=0.0, sample_seconds=60.0, drain_timeout_seconds=3600.0),
            ),
            timeout=5.0,
        )
    assert reads == ["/sessions/s-0"]


async def test_a_running_phase_without_a_running_agent_is_not_active(
    profile: ScriptedAgentProfile, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``running`` from PhaseStarted covers provisioning; the agent session decides."""

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "POST":
            return httpx.Response(200, json={"execution_id": "exec-0", "workflow_id": "w"})
        if path == "/executions":
            return httpx.Response(200, json={"executions": [], "total": 0})
        if path.startswith("/executions/"):
            phase = {"phase_id": "premise", "status": "running", "session_id": "s-0"}
            body = {"workflow_execution_id": "exec-0", "status": "running", "phases": [phase]}
            return httpx.Response(200, json=body)
        return httpx.Response(200, json={"status": "pending", "operations": []})

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        driver.httpx,
        "AsyncClient",
        lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw),
    )
    report = await run_load_test(
        Target("http://stack", "sdlc-implement-v3", "t", ()),
        profile,
        PassBar(n=1, sustain_seconds=0.0, read_p95_seconds=2.0),
        Pacing(admit_seconds=0.0, sample_seconds=0.1, drain_timeout_seconds=0.0),
    )
    assert report.peak_active_phases == 0
    assert report.lost == ["exec-0"]
