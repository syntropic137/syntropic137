"""The load-test pass bar fails the runs it must fail (#1717, #1310 section 6.5)."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from syn_adapters.projections.session_tools import GIT_EVENT_TYPES, SUBAGENT_TOOL_NAMES
from syn_adapters.projections.session_tools_dispatch import to_operation
from syn_domain.contexts.orchestration import WorkflowDefinition
from syn_perf.loadtest import driver
from syn_perf.loadtest.driver import Pacing, Target, parse_docker_stats_line, run_load_test
from syn_perf.loadtest.pass_bar import (
    Admission,
    ContainerRoles,
    ContainerStat,
    Observed,
    PassBar,
    PhaseOutcome,
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
_ROLES = ContainerRoles("syn-api", "syn-db", "syn-event-store", "syn-socket-proxy")
_CONTAINERS = tuple(_ROLES.by_role().values())
_BAR = PassBar(n=4, sustain_seconds=1800.0, read_p95_seconds=0.5, admit_seconds=300.0)


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
    ends: int = _TOOL_USES,
    model: str | None = SCRIPTED_AGENT_MODEL,
    status: str = "completed",
    started_at: str | None = "2026-10-13T08:00:00Z",
) -> RunOutcome:
    phases = tuple(
        PhaseOutcome(p, "completed", f"s-{i}-{p}", stored, ends, model)
        for p in profile.planned_run().ran
    )
    return RunOutcome(f"exec-{i}", True, status, started_at, phases)


def _samples(active: list[int], every: float = 900.0) -> list[Sample]:
    return [Sample(k * every, a, a, 0, 0.1, (0.2,)) for k, a in enumerate(active)]


def _stats() -> list[ContainerStat]:
    return [ContainerStat(c, 10.0, 100) for c in _CONTAINERS]


def _observed(
    samples: list[Sample],
    runs: list[RunOutcome],
    *,
    stats: list[ContainerStat] | None = None,
    admission: Admission | None = None,
) -> Observed:
    return Observed(
        admission=admission or Admission(tuple(r.execution_id for r in runs[:4]), (), 120.0),
        samples=samples,
        runs=runs,
        containers=_stats() if stats is None else stats,
        list_read_query=driver.LIST_READ_QUERY,
    )


def _judge(profile: ScriptedAgentProfile, samples: list[Sample], runs: list[RunOutcome]):
    return judge(_BAR, profile, _observed(samples, runs), _ROLES)


def _failed(report) -> set[str]:
    return {c.name for c in report.checks if not c.passed}


def test_a_clean_run_at_n_passes(profile: ScriptedAgentProfile) -> None:
    report = _judge(profile, _samples([4, 4, 4]), [_run(profile, i) for i in range(4)])
    assert report.passed, report.checks
    assert report.seconds_at_n == 1800.0


def test_a_peak_below_n_is_a_queue_test_and_fails(profile: ScriptedAgentProfile) -> None:
    report = _judge(profile, _samples([3, 3, 3, 3]), [_run(profile, i) for i in range(4)])
    assert _failed(report) == {"concurrency"}
    concurrency = next(c for c in report.checks if c.name == "concurrency")
    assert "queue test" in concurrency.detail
    assert "peak 3" in concurrency.detail


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
        "exec-9",
        True,
        "completed",
        "t",
        (PhaseOutcome("premise", "completed", "s", None, None, SCRIPTED_AGENT_MODEL),),
    )
    report = _judge(profile, _samples([4, 4, 4]), [*runs, unread])
    assert "event_counts" in _failed(report)


def test_a_real_or_unknown_model_fails_the_scripted_check(profile: ScriptedAgentProfile) -> None:
    """At the end, no model is the absence of proof, not a pass (B2)."""
    runs = [
        _run(profile, 0, model="claude-sonnet-5-5"),
        _run(profile, 1, model=None),
        *(_run(profile, i) for i in (2, 3)),
    ]
    report = _judge(profile, _samples([4, 4, 4]), runs)
    assert _failed(report) == {"scripted"}
    assert {u.split("/")[0] for u in report.unscripted_sessions} == {"exec-0", "exec-1"}


def test_failed_missing_and_completion_less_phases_are_mismatches(
    profile: ScriptedAgentProfile,
) -> None:
    """Every planned phase must be present, completed, and hold its starts AND ends (B3)."""
    ran = profile.planned_run().ran
    failed = RunOutcome(
        "exec-0",
        True,
        "failed",
        "t",
        (PhaseOutcome(ran[0], "failed", None, None, None, SCRIPTED_AGENT_MODEL),),
    )
    no_ends = _run(profile, 1, ends=0)
    runs = [failed, no_ends, *(_run(profile, i) for i in (2, 3))]
    report = _judge(profile, _samples([4, 4, 4]), runs)
    assert "event_counts" in _failed(report)
    off = report.event_count_mismatches
    assert f"exec-0/{ran[0]}: failed, not completed" in off
    assert sum(m.startswith("exec-0/") and "phase missing" in m for m in off) == len(ran) - 1
    assert sum(m.startswith("exec-1/") and "0 ends" in m for m in off) == len(ran)


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
    runs = [_run(profile, i) for i in range(4)]
    slow = [Sample(k * 900.0, 4, 4, 0, 0.8, (0.9,)) for k in range(3)]
    report = judge(_BAR, profile, _observed(slow, runs, stats=[]), _ROLES)
    assert _failed(report) == {"list_read_p95", "detail_read_p95", "container_stats"}


def test_omitted_container_roles_fail_by_role(profile: ScriptedAgentProfile) -> None:
    runs = [_run(profile, i) for i in range(4)]
    report = judge(_BAR, profile, _observed(_samples([4, 4, 4]), runs), None)
    assert _failed(report) == {"container_stats"}
    partial = [s for s in _stats() if s.container != _ROLES.socket_proxy]
    report = judge(_BAR, profile, _observed(_samples([4, 4, 4]), runs, stats=partial), _ROLES)
    detail = next(c.detail for c in report.checks if c.name == "container_stats")
    assert detail == "no stats for roles ['socket_proxy']"


def test_a_relaxed_bar_is_not_north_star_certification(profile: ScriptedAgentProfile) -> None:
    runs = [_run(profile, i) for i in range(4)]
    relaxed = PassBar(n=4, sustain_seconds=1800.0, read_p95_seconds=2.0, admit_seconds=300.0)
    report = judge(relaxed, profile, _observed(_samples([4, 4, 4]), runs), _ROLES)
    assert _failed(report) == {"north_star_bar"}


def test_slow_or_incomplete_admission_fails(profile: ScriptedAgentProfile) -> None:
    runs = [_run(profile, i) for i in range(4)]
    ids = tuple(r.execution_id for r in runs)
    late = Admission(ids, (), 301.0)
    report = judge(_BAR, profile, _observed(_samples([4, 4, 4]), runs, admission=late), _ROLES)
    assert _failed(report) == {"admission"}
    short = Admission(ids[:3], ("start 3: HTTP 503",), 10.0)
    report = judge(_BAR, profile, _observed(_samples([4, 4, 4]), runs, admission=short), _ROLES)
    assert _failed(report) == {"admission"}


def test_p95_is_nearest_rank() -> None:
    assert p95([float(v) for v in range(1, 101)]) == 95.0
    assert p95([]) is None


def test_docker_stats_line_parses() -> None:
    line = json.dumps({"Name": "syn-db", "CPUPerc": "12.50%", "MemUsage": "1.5GiB / 2GiB"})
    assert parse_docker_stats_line(line) == ContainerStat("syn-db", 12.5, 1610612736)


# --- the driver against a stand-in API --------------------------------------

_TARGET = Target("http://stack", "sdlc-implement-v3", "t", ("syntropic137/loadtest-fixture",), None)


def _stand_in(monkeypatch: pytest.MonkeyPatch, handler) -> None:
    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        driver.httpx,
        "AsyncClient",
        lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw),
    )


def _converted(tool_names: list[str]) -> list[dict[str, str]]:
    """The session timeline the production converter builds for these tool uses."""
    ops = []
    for k, name in enumerate(tool_names):
        for event_type in ("tool_execution_started", "tool_execution_completed"):
            data = {"tool_name": name, "tool_use_id": f"tu-{k}", "tool_input": {"prompt": "p"}}
            op = to_operation(
                datetime.now(UTC), data, event_type, SUBAGENT_TOOL_NAMES, GIT_EVENT_TYPES
            )
            assert op is not None
            ops.append({"operation_type": op.operation_type})
    return ops


async def test_driver_counts_active_phases_from_the_server(
    profile: ScriptedAgentProfile, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two executions are admitted but only one phase is ever ``running``.

    A driver that counted what it dispatched would report 2; the server says 1.
    Every start carries the fixture repository in its typed ``repos`` field,
    and the dashboard list read is the dashboard's own page shape.
    """
    started: list[str] = []
    bodies: list[dict[str, object]] = []
    list_reads: list[str] = []
    ran = profile.planned_run().ran
    # The second tool use is an Agent: the timeline relabels it subagent_started.
    tools = ["Bash", "Agent"] + ["Read"] * (_TOOL_USES - 2)

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "POST":
            bodies.append(json.loads(request.content))
            started.append(f"exec-{len(started)}")
            return httpx.Response(200, json={"execution_id": started[-1], "workflow_id": "w"})
        if path == "/executions":
            # exec-1 lost its start: the list row has no started_at (#1550).
            q = request.url.params.get("q")
            if q is None:
                list_reads.append(str(request.url.copy_with(scheme=None, host=None)))
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
        # Every session says running; only exec-0's first phase is running too.
        return httpx.Response(
            200,
            json={
                "agent_model": SCRIPTED_AGENT_MODEL,
                "status": "running",
                "operations": _converted(tools),
            },
        )

    _stand_in(monkeypatch, handler)
    report = await run_load_test(
        _TARGET,
        profile,
        PassBar(n=2, sustain_seconds=0.0, read_p95_seconds=2.0),
        Pacing(admit_seconds=0.0, sample_seconds=0.1, drain_timeout_seconds=0.0),
    )
    assert sorted(started) == ["exec-0", "exec-1"]
    assert all(b["repos"] == ["syntropic137/loadtest-fixture"] for b in bodies)
    assert set(list_reads) == {driver.LIST_READ_QUERY}
    assert report.list_read_query == "/executions?page=1&page_size=50"
    assert report.peak_active_phases == 1
    assert "concurrency" in _failed(report)
    # Every completed phase holds an Agent start, relabelled subagent_started,
    # and still matches; only exec-0's still-running phase is off.
    assert report.event_count_mismatches == [f"exec-0/{ran[0]}: running, not completed"]
    assert report.dropped_starts == ["exec-1"]
    assert report.lost == []


async def test_a_rejected_start_keeps_the_admitted_one(
    profile: ScriptedAgentProfile, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One start succeeds and the next gets 503: the report still accounts for both (B5)."""
    posts: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "POST":
            posts.append(len(posts))
            if len(posts) == 2:
                return httpx.Response(503, text="budget full")
            return httpx.Response(200, json={"execution_id": "exec-0", "workflow_id": "w"})
        if path == "/executions":
            q = request.url.params.get("q")
            rows = [{"workflow_execution_id": q, "status": "completed", "started_at": "t"}]
            return httpx.Response(200, json={"executions": rows if q else [], "total": 1})
        body = {"workflow_execution_id": "exec-0", "status": "completed", "phases": []}
        return httpx.Response(200, json=body)

    _stand_in(monkeypatch, handler)
    report = await run_load_test(
        _TARGET,
        profile,
        PassBar(n=2, sustain_seconds=0.0, read_p95_seconds=2.0),
        Pacing(admit_seconds=0.0, sample_seconds=0.1, drain_timeout_seconds=0.0),
    )
    assert report.admitted == ["exec-0"]
    assert report.admission_rejected == ["start 1: HTTP 503 budget full"]
    assert "admission" in _failed(report)
    assert report.lost == []


async def test_driver_stops_at_the_first_real_model(
    profile: ScriptedAgentProfile, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A real harness stops further admissions on the tick it is seen, and still reports."""
    reads: list[str] = []
    posts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "POST":
            posts.append(f"exec-{len(posts)}")
            return httpx.Response(200, json={"execution_id": posts[-1], "workflow_id": "w"})
        if path == "/executions":
            q = request.url.params.get("q")
            rows = [{"workflow_execution_id": q, "status": "running", "started_at": "t"}]
            return httpx.Response(200, json={"executions": rows if q else [], "total": 0})
        if path.startswith("/executions/"):
            eid = path.rsplit("/", 1)[1]
            phase = {"phase_id": "premise", "status": "running", "session_id": f"s-{eid}"}
            body = {"workflow_execution_id": eid, "status": "running", "phases": [phase]}
            return httpx.Response(200, json=body)
        reads.append(path)
        return httpx.Response(200, json={"agent_model": "claude-opus-5-5", "operations": []})

    _stand_in(monkeypatch, handler)
    report = await asyncio.wait_for(
        run_load_test(
            _TARGET,
            profile,
            # Ten starts paced a second apart: the first tick that sees exec-0's
            # real model must stop the other nine from ever being sent.
            PassBar(n=10, sustain_seconds=3600.0, read_p95_seconds=2.0),
            Pacing(admit_seconds=10.0, sample_seconds=0.2, drain_timeout_seconds=3600.0),
        ),
        timeout=5.0,
    )
    assert report.refused is not None
    assert "claude-opus-5-5" in report.refused
    assert len(posts) < 10
    assert report.admitted == posts
    assert {"refused", "scripted"} <= _failed(report)


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

    _stand_in(monkeypatch, handler)
    report = await run_load_test(
        _TARGET,
        profile,
        PassBar(n=1, sustain_seconds=0.0, read_p95_seconds=2.0),
        Pacing(admit_seconds=0.0, sample_seconds=0.1, drain_timeout_seconds=0.0),
    )
    assert report.peak_active_phases == 0
    assert report.lost == ["exec-0"]


async def test_a_start_passes_the_api_repository_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    """The driver's start body clears the API's real ADR-058 guard for implement-v3 (B1).

    The workflow requires a repository and declares none, so a body without
    ``repos`` is a 422 there. Only the GitHub access check is replaced: it is
    a network call, and it must receive the fixture repository.
    """
    from fastapi import HTTPException

    from syn_api.routes.executions import commands
    from syn_domain.contexts._shared.repository_ref import RepositoryRef
    from syn_domain.contexts.orchestration._shared.yaml_to_command import (
        build_command_from_definition,
    )
    from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.WorkflowTemplateAggregate import (
        WorkflowTemplateAggregate,
    )

    definition = WorkflowDefinition.from_file(_WORKFLOW)
    template = WorkflowTemplateAggregate()
    template.create_workflow(build_command_from_definition(definition))
    checked: list[object] = []

    async def access(repos: object) -> None:
        checked.append(repos)

    monkeypatch.setattr(commands, "_validate_all_repos_access", access)

    async def guard(target: Target) -> None:
        request = commands.ExecuteWorkflowRequest.model_validate(driver.start_body(target))
        typed = [RepositoryRef.parse(r) for r in request.repos]
        merged = commands._merge_inputs(template, dict(request.inputs), request.task)
        await commands._preflight_repos_or_reject(
            template, definition.id, typed, dict(request.inputs), merged, request.task
        )

    await guard(_TARGET)
    assert len(checked) == 1
    assert "syntropic137/loadtest-fixture" in str(checked[0])
    with pytest.raises(HTTPException) as refused:
        await guard(Target("http://stack", definition.id, "t", (), None))
    assert refused.value.status_code == 422
