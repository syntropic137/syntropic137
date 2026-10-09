"""Latency gate: executions, sessions and artifacts read in milliseconds (E2).

The owner: "whenever I try to look at the executions page or sessions page or
the dashboard page, it takes forever to load." Measured live (flywheel,
2026-10-04, avg of 3): /executions 3.57s, /executions/{id} 4.38s, /sessions
1.75-2.87s, /artifacts 7.65s.

WHAT IS TIMED. The real endpoints, end to end, through the FastAPI app against
a real TimescaleDB holding both stores they read (ADR-030): the observability
hypertable (Lane 2) and the projection store (Lane 1). Same harness as the E1
gate beside this file (test_dashboard_latency_budget.py); see it for why this
is an integration test and where CI runs it.

THE DATASET is shaped like a long-lived install: 2,000 executions of three
phases each, so 6,000 sessions, each with 60 turns, 30 tool observations, a
summary and a capture observation - about 570k observability rows over ninety
days - and one artifact per phase carrying a few KB of markdown. Every chunk
older than a day is COMPRESSED, as the live policy does, because that is the
shape that made the old execution-keyed reads slow: `execution_id` is in
neither compression key, so a compressed chunk cannot be narrowed by it.

THE BUDGETS are the E2 targets: p95 <= 200ms for a list, <= 300ms for a detail.
Measured numbers, before and after, are in the PR description.

THE REPOS PAGE (owner feedback 0afb5d92: "takes like five seconds to load")
waits on /repos, /systems and /github/repos together. The first two read the
seeded organization projections. /github/repos answers from the App's cached
listing, seeded here as EXPIRED, the state a page opened after a while away
finds, while every GitHub call takes GITHUB_ROUND_TRIP_S: a request that waited
on GitHub cannot fit its budget.
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from syn_shared.events import SESSION_STARTED, SESSION_SUMMARY, TOKEN_USAGE

if TYPE_CHECKING:
    import asyncpg
    import httpx

    from syn_domain.pagination import ProjectionRecord

pytestmark = pytest.mark.integration

os.environ.setdefault("APP_ENVIRONMENT", "test")

EXECUTIONS = 2_000
PHASES = 3
WORKFLOWS = 100
TURNS_PER_SESSION = 60
TOOL_EVENTS_PER_SESSION = 30
DAYS = 240
RUNS = 20
WARMUP = 2

LIST_BUDGET_MS = 200.0
DETAIL_BUDGET_MS = 300.0

# Feedback 60d9f990: a list opens at 100 rows only if 100 costs at most 1.5x
# of 50. On the VPS Sessions measured 0.85-1.22x, so Sessions opens at 100 and
# that page is gated; Executions measured up to 2.04x, so it opens at 50 and
# 100 is the operator's choice, timed for its ratio. The ratios are printed so
# the next measurement is one run away.
MAX_100_OVER_50 = 1.5

# The repos page: registered repos spread over systems, and an App that reaches
# them plus some only it knows about.
REPOS = 500
SYSTEMS = 25
APP_ONLY_REPOS = 100
REPOS_PAGE_BUDGET_MS = 300.0
GITHUB_ROUND_TRIP_S = 2.0

# The execution the detail endpoint is timed on: mid-history, so its rows sit
# in a compressed chunk like almost every execution an operator opens.
DETAIL_EXECUTION = 777


@dataclass(frozen=True)
class Endpoint:
    """One gated request and the p95 it must stay under."""

    name: str
    path: str
    params: dict[str, str]
    budget_ms: float
    #: False for a size no page opens at: timed for its ratio, not gated.
    gated: bool = True


ENDPOINTS: tuple[Endpoint, ...] = (
    Endpoint(
        "/executions?page_size=50",
        "/executions",
        {"page": "1", "page_size": "50"},
        LIST_BUDGET_MS,
    ),
    # 100 rows, timed beside 50 so the cost of the larger page is a number
    # (feedback 60d9f990). Executions opens at 50, so this is not gated.
    Endpoint(
        "/executions?page_size=100",
        "/executions",
        {"page": "1", "page_size": "100"},
        LIST_BUDGET_MS,
        gated=False,
    ),
    Endpoint(
        "/executions/{id}",
        f"/executions/exec-{DETAIL_EXECUTION:05d}",
        {},
        DETAIL_BUDGET_MS,
    ),
    Endpoint(
        "/sessions?page_size=20", "/sessions", {"page": "1", "page_size": "20"}, LIST_BUDGET_MS
    ),
    Endpoint(
        "/sessions?page_size=50", "/sessions", {"page": "1", "page_size": "50"}, LIST_BUDGET_MS
    ),
    # Sessions opens at 100 (SESSION_LIST_PAGE_SIZE), so this one is gated.
    Endpoint(
        "/sessions?page_size=100",
        "/sessions",
        {"page": "1", "page_size": "100"},
        LIST_BUDGET_MS,
    ),
    Endpoint("/artifacts?page_size=20", "/artifacts", {"page_size": "20"}, LIST_BUDGET_MS),
    # The three requests the repos page makes together (feedback 0afb5d92).
    Endpoint("/repos", "/repos", {}, REPOS_PAGE_BUDGET_MS),
    Endpoint("/systems", "/systems", {}, REPOS_PAGE_BUDGET_MS),
    Endpoint("/github/repos", "/github/repos", {}, REPOS_PAGE_BUDGET_MS),
)

_COLUMNS = ("time", "event_type", "session_id", "execution_id", "phase_id", "data")
_Row = tuple[datetime, str, str, str, str, str]


def repo_name(n: int) -> str:
    return f"acme/repo-{n:04d}"


def execution_id(n: int) -> str:
    return f"exec-{n:05d}"


def session_id(n: int, phase: int) -> str:
    return f"sess-{n:05d}-{phase}"


def workflow_id(n: int) -> str:
    return f"wf-{n % WORKFLOWS}"


def started_at(now: datetime, n: int) -> datetime:
    """Newest execution first: n = 0 is now, the last one ninety days ago."""
    return now - timedelta(minutes=n * (DAYS * 24 * 60) // EXECUTIONS + 5)


def model_of(n: int, phase: int) -> str:
    return ("claude-sonnet-5", "claude-haiku-4-5-20251001", "claude-opus-5")[(n + phase) % 3]


def _session_rows(now: datetime, n: int, phase: int) -> list[_Row]:
    execution = execution_id(n)
    session = session_id(n, phase)
    phase_id = f"p{phase}"
    start = started_at(now, n) + timedelta(minutes=10 * phase)
    model = model_of(n, phase)

    def at(i: int) -> datetime:
        return start + timedelta(seconds=i)

    rows: list[_Row] = [(at(0), SESSION_STARTED, session, execution, phase_id, "{}")]
    turn = json.dumps(
        {"model": model, "input_tokens": 100, "output_tokens": 7, "cache_read_tokens": 900}
    )
    rows.extend(
        (at(1 + i), TOKEN_USAGE, session, execution, phase_id, turn)
        for i in range(TURNS_PER_SESSION)
    )
    for i in range(TOOL_EVENTS_PER_SESSION):
        tool = json.dumps(
            {
                "tool_name": "Bash",
                "tool_use_id": f"t{i}",
                "success": True,
                "duration_ms": 120,
                "output": "x" * 400,
            }
        )
        rows.append((at(100 + i), "tool_execution_completed", session, execution, phase_id, tool))
    capture = json.dumps({"schema_version": 2, "agent_session_ids": [f"agent-{session}"]})
    rows.append((at(200), "session_capture", session, execution, phase_id, capture))
    # Most sessions finish; the rest are priced from their turns.
    if (n + phase) % 7:
        summary = json.dumps(
            {
                "model": model,
                "total_input_tokens": 6_000,
                "total_output_tokens": 420,
                "cache_read_tokens": 54_000,
                "total_cost_usd": 0.05 + phase / 100,
                "num_turns": TURNS_PER_SESSION,
                "duration_ms": 300_000,
            }
        )
        rows.append((at(300), SESSION_SUMMARY, session, execution, phase_id, summary))
    return rows


def observability_rows(now: datetime) -> list[_Row]:
    """The seeded agent_events rows, deterministic so every run times the same work."""
    rows: list[_Row] = []
    for n in range(EXECUTIONS):
        for phase in range(PHASES):
            rows.extend(_session_rows(now, n, phase))
    return rows


def artifact_content(n: int, phase: int) -> str:
    """A few KB of markdown, varied so TOAST compression cannot erase it."""
    line = f"- finding {n}.{phase}: {uuid.UUID(int=n * 7 + phase)} " * 4
    return f"# Phase {phase} report for {execution_id(n)}\n\n" + "\n".join(
        f"{i:04d} {line}" for i in range(20 + (n % 40))
    )


class _DictStore:
    """Just enough of a projection store to run the real handlers in memory.

    The documents the gate seeds are produced by the projections' own handlers,
    so their shape is exactly what production writes. Running them against
    Postgres one event at a time would make seeding take minutes; this runs
    them in memory and the result is bulk-inserted below.
    """

    def __init__(self) -> None:
        self.tables: dict[str, dict[str, ProjectionRecord]] = {}

    async def get(self, projection: str, key: str) -> ProjectionRecord | None:
        record = self.tables.get(projection, {}).get(key)
        # A fresh copy, as a database read is: handlers mutate what they get.
        return json.loads(json.dumps(record)) if record is not None else None

    async def save(self, projection: str, key: str, data: ProjectionRecord) -> None:
        self.tables.setdefault(projection, {})[key] = json.loads(json.dumps(data, default=str))


async def projection_documents(now: datetime) -> dict[str, dict[str, ProjectionRecord]]:
    """Every Lane 1 document the five endpoints read, built by the real handlers."""
    from syn_domain.contexts.agent_sessions.slices.list_sessions.projection import (
        SessionListProjection,
    )
    from syn_domain.contexts.artifacts.slices.list_artifacts.projection import (
        ArtifactListProjection,
    )
    from syn_domain.contexts.orchestration.slices.get_execution_detail.projection import (
        WorkflowExecutionDetailProjection,
    )
    from syn_domain.contexts.orchestration.slices.list_executions.projection import (
        WorkflowExecutionListProjection,
    )

    store = _DictStore()
    listing = WorkflowExecutionListProjection(store)  # type: ignore[arg-type]  # duck-typed store
    detail = WorkflowExecutionDetailProjection(store)  # type: ignore[arg-type]
    sessions = SessionListProjection(store)  # type: ignore[arg-type]
    artifacts = ArtifactListProjection(store)
    for n in range(EXECUTIONS):
        execution = execution_id(n)
        start = started_at(now, n)
        started = {
            "execution_id": execution,
            "workflow_id": workflow_id(n),
            "workflow_name": f"Workflow {n % WORKFLOWS}",
            "started_at": start.isoformat(),
            "total_phases": PHASES,
            "inputs": {"repos": "syntropic137/syntropic137", "task": f"task {n}"},
            "tags": ["gate"] if n % 4 == 0 else [],
            "phase_definitions": [
                {"phase_id": f"p{p}", "timeout_seconds": 1800} for p in range(PHASES)
            ],
        }
        await listing.on_workflow_execution_started(started)
        await detail.on_workflow_execution_started(started)
        for phase in range(PHASES):
            session = session_id(n, phase)
            phase_start = start + timedelta(minutes=10 * phase)
            phase_end = phase_start + timedelta(minutes=5)
            artifact = f"art-{n:05d}-{phase}"
            await detail.on_phase_started(
                {
                    "execution_id": execution,
                    "phase_id": f"p{phase}",
                    "phase_name": f"Phase {phase}",
                    "session_id": session,
                    "started_at": phase_start.isoformat(),
                }
            )
            await sessions.on_session_started(
                {
                    "session_id": session,
                    "workflow_id": workflow_id(n),
                    "agent_provider": "claude",
                    "started_at": phase_start.isoformat(),
                    "phase_id": f"p{phase}",
                    "execution_id": execution,
                    "root_session_id": session,
                }
            )
            await sessions.on_session_completed(
                {
                    "session_id": session,
                    "status": "completed",
                    "completed_at": phase_end.isoformat(),
                    "total_input_tokens": 6_000,
                    "total_output_tokens": 420,
                    "total_cache_read_tokens": 54_000,
                    "total_tokens": 60_420,
                }
            )
            content = artifact_content(n, phase)
            await artifacts.on_artifact_created(
                {
                    "artifact_id": artifact,
                    "workflow_id": workflow_id(n),
                    "execution_id": execution,
                    "session_id": session,
                    "phase_id": f"p{phase}",
                    "artifact_type": ("report", "plan", "code")[phase],
                    "title": f"Phase {phase} report",
                    "created_at": phase_end.isoformat(),
                    "content": content,
                    "agent_provider": "claude",
                    "agent_model": model_of(n, phase),
                }
            )
            completed = {
                "execution_id": execution,
                "phase_id": f"p{phase}",
                "session_id": session,
                "artifact_id": artifact,
                "input_tokens": 6_000,
                "output_tokens": 420,
                "cache_read_tokens": 54_000,
                "total_tokens": 60_420,
                "duration_seconds": 300.0,
                "completed_at": phase_end.isoformat(),
                "tool_call_count": TOOL_EVENTS_PER_SESSION,
            }
            await detail.on_phase_completed(completed)
            await listing.on_phase_completed(completed)
        # The newest few are still running; everything else finished.
        if n >= 5:
            done = {
                "execution_id": execution,
                "completed_at": (start + timedelta(minutes=10 * PHASES)).isoformat(),
                "completed_phases": PHASES,
                "total_tokens": 60_420 * PHASES,
            }
            await listing.on_workflow_completed(done)
            await detail.on_workflow_completed(done)
    await seed_organization(store)
    return store.tables


async def seed_organization(store: _DictStore) -> None:
    """Systems and registered repos, built by the organization projections' handlers."""
    from syn_domain.contexts.organization.slices.list_repos.projection import RepoProjection
    from syn_domain.contexts.organization.slices.list_systems.projection import SystemProjection

    repos = RepoProjection(store)  # type: ignore[arg-type]  # duck-typed store
    systems = SystemProjection(store)  # type: ignore[arg-type]
    for s in range(SYSTEMS):
        await systems.on_system_created(
            {"system_id": f"sys-{s:02d}", "organization_id": "org-1", "name": f"System {s}"}
        )
    for n in range(REPOS):
        # Every fifth repo belongs to no system.
        system = f"sys-{n % SYSTEMS:02d}" if n % 5 else ""
        registered = {
            "repo_id": f"repo-{n:04d}",
            "organization_id": "org-1",
            "system_id": system,
            "provider": "github",
            "full_name": repo_name(n),
            "owner": "acme",
            "installation_id": "inst-1",
        }
        await repos.on_repo_registered(registered)
        await systems.on_repo_registered_increment(registered)


async def seed(pool: asyncpg.Pool, now: datetime) -> None:
    """Both stores, seeded the way production writes them, then compressed."""
    from syn_adapters.projection_stores import get_projection_store

    store = get_projection_store()
    documents = await projection_documents(now)
    async with pool.acquire() as conn:
        # COPY, as insert_batch does in production, so every trigger on
        # agent_events sees these rows exactly the way it sees real ones.
        await conn.copy_records_to_table(
            "agent_events", records=observability_rows(now), columns=_COLUMNS
        )
    for projection, records in documents.items():
        # Created by the store itself, so the table has the indexes it has live.
        await store._ensure_table(projection)  # type: ignore[attr-defined]  # Postgres store
        table = store._table_name(projection)  # type: ignore[attr-defined]
        base = now - timedelta(days=DAYS)
        async with pool.acquire() as conn:
            await conn.executemany(
                f"INSERT INTO {table} (id, data, updated_at) VALUES ($1, $2::jsonb, $3)",
                [
                    (key, json.dumps(doc), base + timedelta(seconds=i))
                    for i, (key, doc) in enumerate(records.items())
                ],
            )
    async with pool.acquire() as conn:
        # What the live compression policy has done to everything older than a day.
        await conn.execute(
            "SELECT compress_chunk(c, if_not_compressed => TRUE) "
            "FROM show_chunks('agent_events', older_than => INTERVAL '1 day') c"
        )
        await conn.execute("VACUUM ANALYZE")


class SlowGitHub:
    """A GitHub App whose every call takes GITHUB_ROUND_TRIP_S, as a real round-trip does.

    The installation list then fails, so a background refresh never replaces
    the expired listing and every timed request meets the expired-cache path.
    """

    async def list_installations(self) -> list[dict]:
        await asyncio.sleep(GITHUB_ROUND_TRIP_S)
        raise RuntimeError("GitHub 502")

    async def list_accessible_repos(self, installation_id: str | None = None) -> list[dict]:
        await asyncio.sleep(GITHUB_ROUND_TRIP_S)
        return [
            {"id": n, "name": repo_name(n).split("/")[1], "full_name": repo_name(n)}
            for n in range(REPOS + APP_ONLY_REPOS)
        ]


async def seed_expired_app_listing() -> None:
    """The App listing a page opened after a while away finds: cached, but expired."""
    from syn_api.services.github_repo_listing_cache import (
        FRESH_FOR,
        CachedRepoListing,
        get_repo_listing_cache,
    )
    from syn_api.types import GitHubRepoResponse

    cache = get_repo_listing_cache()
    generation = await cache.generation()
    assert generation is not None
    repos = [
        GitHubRepoResponse(
            github_id=n,
            name=repo_name(n).split("/")[1],
            full_name=repo_name(n),
            private=False,
            default_branch="main",
            owner="acme",
            installation_id="inst-1",
        )
        for n in range(REPOS + APP_ONLY_REPOS)
    ]
    expired_at = datetime.now(UTC) - FRESH_FOR - timedelta(minutes=30)
    await cache.put(CachedRepoListing(repos=repos, fetched_at=expired_at, generation=generation))


def use_timescale_timeline(pool: asyncpg.Pool) -> None:
    """Read phase timelines from the hypertable, as production does.

    Under APP_ENVIRONMENT=test the manager wires the in-memory timeline
    (manager_registry.create_session_tools_projection), which would leave the
    detail endpoint's per-phase timeline read out of the timing entirely.
    """
    from syn_adapters.projections.session_tools import SessionToolsProjection
    from syn_api._wiring import get_projection_mgr

    manager = get_projection_mgr()
    manager._ensure_initialized()  # the registry is built lazily; replace after it is
    manager._projections["session_tools"] = SessionToolsProjection(pool)


async def p95_ms(client: httpx.AsyncClient, path: str, params: dict[str, str]) -> float:
    for _ in range(WARMUP):
        (await client.get(path, params=params)).raise_for_status()
    samples: list[float] = []
    for _ in range(RUNS):
        started = time.perf_counter()
        response = await client.get(path, params=params)
        samples.append((time.perf_counter() - started) * 1000)
        response.raise_for_status()
    samples.sort()
    return samples[math.ceil(0.95 * len(samples)) - 1]


async def assert_timing_real_work(client: httpx.AsyncClient) -> None:
    """The gate must be timing real work, not an empty table or an error body."""
    executions = (await client.get("/executions", params={"page_size": "50"})).json()
    assert executions["total"] == EXECUTIONS, executions["total"]
    assert len(executions["executions"]) == 50
    assert executions["executions"][0]["workflow_execution_id"] == execution_id(0)
    assert executions["executions"][-1]["total_cost_usd"] not in (0, "0", "0.0"), executions[
        "executions"
    ][-1]
    detail = (await client.get(f"/executions/{execution_id(DETAIL_EXECUTION)}")).json()
    assert len(detail["phases"]) == PHASES, detail
    assert all(p["operations"] for p in detail["phases"]), detail["phases"]
    assert all(p["agent_session_ids"] for p in detail["phases"]), detail["phases"]
    sessions = (await client.get("/sessions", params={"page_size": "50"})).json()
    assert sessions["total"] == EXECUTIONS * PHASES, sessions["total"]
    assert len(sessions["sessions"]) == 50
    # The 100-row pages are timed over 100 rows, not a short page.
    for path, rows in (("/executions", "executions"), ("/sessions", "sessions")):
        page = (await client.get(path, params={"page_size": "100"})).json()
        assert len(page[rows]) == 100, (path, len(page[rows]))
    artifacts = (await client.get("/artifacts", params={"page_size": "20"})).json()
    assert artifacts["total"] == EXECUTIONS * PHASES, artifacts["total"]
    assert len(artifacts["artifacts"]) == 20
    repos = (await client.get("/repos")).json()
    assert repos["total"] == REPOS, repos["total"]
    systems = (await client.get("/systems")).json()
    assert systems["total"] == SYSTEMS, systems["total"]
    assert sum(s["repo_count"] for s in systems["systems"]) == REPOS * 4 // 5
    app = (await client.get("/github/repos")).json()
    assert (app["total"], app["lookup"]) == (REPOS + APP_ONLY_REPOS, "partial"), app["lookup"]


def over_budget(measured: dict[str, float]) -> list[str]:
    """The gated endpoints whose measured p95 is over their budget."""
    return [e.name for e in ENDPOINTS if e.gated and measured[e.name] > e.budget_ms]


async def test_list_and_detail_endpoints_stay_inside_their_p95_budget(
    e2_seeded_client: httpx.AsyncClient,
) -> None:
    client = e2_seeded_client
    await assert_timing_real_work(client)

    measured = {e.name: await p95_ms(client, e.path, e.params) for e in ENDPOINTS}

    table = "\n".join(
        f"  {e.name:<28} p95 {measured[e.name]:8.1f} ms   budget {e.budget_ms:5.0f} ms"
        for e in ENDPOINTS
    )
    print(f"\nE2 latency gate ({RUNS} runs per endpoint):\n{table}")
    ratios = {
        name: measured[f"{name}?page_size=100"] / measured[f"{name}?page_size=50"]
        for name in ("/executions", "/sessions")
    }
    for name, ratio in ratios.items():
        verdict = "within" if ratio <= MAX_100_OVER_50 else "OVER"
        print(f"  {name} p95 at 100 rows / at 50 rows: {ratio:.2f}x ({verdict} {MAX_100_OVER_50}x)")
    over = over_budget(measured)
    assert not over, f"p95 over budget for {over}:\n{table}"
