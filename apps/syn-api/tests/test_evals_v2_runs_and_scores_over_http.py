"""Evals v2 over HTTP: runs as data points, scores, pass rate and variants.

Through the real app, routes, handlers, aggregates, event-store repositories and
read models. The only seam stubbed is Lane 2 - the session and execution cost
queries - because that is where the OBSERVED model and the cost come from, and
it is TimescaleDB in production. Every phase below DECLARES the alias ``opus``
or ``sonnet``; only the stub knows the concrete model, so a run reporting the
alias, or a variant grouping by it, fails here.
"""

from __future__ import annotations

import os

os.environ.setdefault("APP_ENVIRONMENT", "test")

from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from httpx import ASGITransport, AsyncClient

from syn_api.routes.executions.models import ExecutionListResponse
from syn_api.types import ExecutionEvalRunResponse
from syn_domain.contexts.agent_sessions.domain.read_models.session_cost import SessionCost
from syn_domain.contexts.orchestration import TagSet, WorkflowExecutionAggregate
from syn_domain.contexts.orchestration._shared.eval_choice import EvalSelection, LaunchEval
from syn_domain.contexts.orchestration.domain.aggregate_eval import EvalId
from syn_domain.contexts.orchestration.domain.aggregate_execution.commands import (
    StartExecutionCommand,
    StartPhaseCommand,
)
from syn_domain.contexts.orchestration.domain.read_models.execution_cost import ExecutionCost
from syn_domain.testing.fake_revision_resolver import FakeRevisionResolver
from syn_shared.observed_model import UNKNOWN_MODEL_KEY

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator

pytestmark = [pytest.mark.unit, pytest.mark.anyio]

SHA = "c" * 40
OPUS = "claude-opus-5-5"
SONNET = "claude-sonnet-5"
_ALIAS_OF = {OPUS: "opus", SONNET: "sonnet"}


@pytest.fixture(autouse=True)
def _reset_storage() -> Iterator[None]:
    from syn_adapters.projection_stores import get_projection_store
    from syn_adapters.projections.manager import reset_projection_manager
    from syn_adapters.storage import reset_storage

    reset_storage()
    reset_projection_manager()
    store = get_projection_store()
    if hasattr(store, "_data"):
        store._data.clear()  # pyright: ignore[reportAttributeAccessIssue]  # in-memory store only
    if hasattr(store, "_state"):
        store._state.clear()  # pyright: ignore[reportAttributeAccessIssue]  # in-memory store only
    yield
    reset_storage()
    reset_projection_manager()


class _Lane2:
    """What TimescaleDB would answer: per session, the model that RAN; per run, its cost."""

    def __init__(self) -> None:
        self.observed: dict[str, str] = {}
        self.costs: dict[str, Decimal] = {}
        self.by_phase: dict[str, dict[str, dict[str, Decimal]]] = {}
        self.unpriced: dict[str, int] = {}

    async def get_session_cost(self, session_id: str) -> SessionCost | None:
        model = self.observed.get(session_id)
        if model is None:
            return None
        return SessionCost(
            session_id=session_id, agent_model=model, requested_model=_ALIAS_OF[model]
        )

    async def get_execution_cost(self, execution_id: str) -> ExecutionCost | None:
        cost = self.costs.get(execution_id)
        if cost is None:
            return None
        return ExecutionCost(
            execution_id=execution_id,
            total_cost_usd=cost,
            input_tokens=10,
            output_tokens=10,
            models_by_phase=self.by_phase.get(execution_id, {}),
            unpriced_observation_count=self.unpriced.get(execution_id, 0),
        )


@pytest.fixture
async def lane2(monkeypatch: pytest.MonkeyPatch) -> _Lane2:
    from syn_api._wiring import ensure_connected, get_projection_mgr

    await ensure_connected()
    fake = _Lane2()
    manager = get_projection_mgr()
    monkeypatch.setattr(manager.session_cost, "get_session_cost", fake.get_session_cost)
    monkeypatch.setattr(manager.execution_cost, "get_execution_cost", fake.get_execution_cost)
    return fake


@pytest.fixture
async def client(monkeypatch: pytest.MonkeyPatch, lane2: _Lane2) -> AsyncIterator[AsyncClient]:
    from syn_api.main import create_app

    fake = FakeRevisionResolver(shas={("acme/app", "main"): SHA})
    monkeypatch.setattr("syn_api.routes.evals.get_revision_resolver", lambda: fake)
    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://t") as c:
        yield c


async def _catch_up() -> None:
    """Replay the store into the eval read model, as the coordinator would."""
    from event_sourcing.client.memory import MemoryEventStoreClient
    from event_sourcing.stores.memory_checkpoint import MemoryCheckpointStore

    from syn_adapters.projections.manager import get_projection_manager
    from syn_adapters.storage.event_store_client import get_event_store_client
    from syn_domain.testing.stored_replay import replay

    store_client = get_event_store_client()
    assert isinstance(store_client, MemoryEventStoreClient)
    await replay(store_client, MemoryCheckpointStore(), get_projection_manager().eval_list)


async def _create(client: AsyncClient) -> str:
    response = await client.post(
        "/evals",
        json={
            "name": "verifier-seed: case-1",
            "goal": "Does the verifier refuse a bad change?",
            "baseline_repos": [{"repository": "acme/app", "requested_ref": "main"}],
            "tags": ["suite:verifier-seed", "case:case-1"],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["eval_id"]


async def _run(
    lane2: _Lane2,
    eval_id: str | None,
    execution_id: str,
    workflow_id: str,
    model: str,
    cost: str,
    started_at: str,
    workflow_version: str | None = None,
) -> None:
    """A run whose one phase was declared as an alias and RAN ``model``."""
    from syn_api._wiring import (
        get_workflow_execution_repository,
        sync_published_events_to_projections,
    )

    session_id = f"sess-{execution_id}"
    aggregate = WorkflowExecutionAggregate()
    aggregate._handle_command(  # pyright: ignore[reportPrivateUsage]
        StartExecutionCommand(
            execution_id=execution_id,
            workflow_id=workflow_id,
            workflow_name=workflow_id,
            total_phases=1,
            inputs={},
            tags=TagSet(),
            launch_eval=None
            if eval_id is None
            else LaunchEval(EvalId(eval_id), EvalSelection.EXPLICIT),
            workflow_version=workflow_version,
        )
    )
    aggregate._handle_command(  # pyright: ignore[reportPrivateUsage]
        StartPhaseCommand(
            execution_id=execution_id,
            workflow_id=workflow_id,
            phase_id="verify",
            phase_name="Verify",
            phase_order=0,
            session_id=session_id,
        )
    )
    await get_workflow_execution_repository().save_new(aggregate)
    await sync_published_events_to_projections()
    lane2.observed[session_id] = model
    lane2.costs[execution_id] = Decimal(cost)
    await _pin_started_at(execution_id, started_at)


async def _pin_started_at(execution_id: str, started_at: str) -> None:
    """Runs start within one test's milliseconds; spread them so "newest" is decidable."""
    from syn_adapters.projections.manager import get_projection_manager

    store = get_projection_manager().store
    row = await store.get("workflow_executions", execution_id)
    assert row is not None
    await store.save("workflow_executions", execution_id, {**row, "started_at": started_at})


async def _complete_with_an_unmeasured_phase(execution_id: str, *, verify_seconds: float) -> None:
    """Rewrite the run's DETAIL record as a completed execution with two phases:
    ``verify`` took ``verify_seconds``; ``review`` finished with no recorded
    duration and no timestamps, so nobody knows how long it took (#890).

    Stored exactly as the projection stores phases, so the real ``get_detail``
    resolves the durations and counts the unknown phase itself.
    """
    from syn_adapters.projections.manager import get_projection_manager

    store = get_projection_manager().store
    row = await store.get("workflow_execution_details", execution_id)
    assert row is not None
    [verify] = row["phases"]
    phases = [
        {
            **verify,
            "status": "completed",
            "started_at": "2026-10-01T00:00:00+00:00",
            "completed_at": "2026-10-01T00:05:00+00:00",
            "duration_seconds": verify_seconds,
        },
        {
            **verify,
            "workflow_phase_id": "review",
            "name": "Review",
            "status": "completed",
            "session_id": None,
            "started_at": None,
            "completed_at": None,
            "duration_seconds": None,
        },
    ]
    await store.save(
        "workflow_execution_details",
        execution_id,
        {**row, "status": "completed", "phases": phases},
    )


async def _score(client: AsyncClient, eval_id: str, execution_id: str, verdict: str):
    return await client.post(
        f"/evals/{eval_id}/runs/{execution_id}/score",
        json={
            "verdict": verdict,
            "score": 1.0 if verdict == "PASS" else 0.0,
            "evidence": f"## {verdict}\n\nchecked {execution_id}",
            "scorer": "eval_suite.py",
            "scorer_version": "2",
        },
    )


async def _two_by_two(client: AsyncClient, lane2: _Lane2) -> str:
    """Two workflows x two observed models, one eval; wf-a/opus has two runs."""
    eval_id = await _create(client)
    runs = [
        ("r1", "wf-a", OPUS, "1.00", "2026-10-01T00:00:00+00:00", "PASS"),
        ("r2", "wf-a", OPUS, "3.00", "2026-10-02T00:00:00+00:00", "FAIL"),
        ("r3", "wf-a", SONNET, "0.50", "2026-10-03T00:00:00+00:00", "PASS"),
        ("r4", "wf-b", OPUS, "2.00", "2026-10-04T00:00:00+00:00", "ERROR"),
        ("r5", "wf-b", SONNET, "0.25", "2026-10-05T00:00:00+00:00", None),
    ]
    for execution_id, workflow_id, model, cost, started_at, verdict in runs:
        version = "2.0.0" if execution_id == "r2" else "1.0.0"
        await _run(lane2, eval_id, execution_id, workflow_id, model, cost, started_at, version)
        if verdict is not None:
            response = await _score(client, eval_id, execution_id, verdict)
            assert response.status_code == 200, response.text
    await _catch_up()
    return eval_id


class TestRuns:
    async def test_a_run_reports_the_model_that_ran_not_the_alias(
        self, client: AsyncClient, lane2: _Lane2
    ) -> None:
        eval_id = await _two_by_two(client, lane2)

        body = (await client.get(f"/evals/{eval_id}/runs")).json()

        by_id = {row["execution_id"]: row for row in body["items"]}
        assert by_id["r3"]["models"] == [{"phase_id": "verify", "model": SONNET}]
        assert by_id["r1"]["models"] == [{"phase_id": "verify", "model": OPUS}]
        assert all(m["model"] not in ("opus", "sonnet") for r in body["items"] for m in r["models"])

    async def test_runs_are_newest_first_with_cost_and_score(
        self, client: AsyncClient, lane2: _Lane2
    ) -> None:
        eval_id = await _two_by_two(client, lane2)

        body = (await client.get(f"/evals/{eval_id}/runs")).json()

        assert [row["execution_id"] for row in body["items"]] == ["r5", "r4", "r3", "r2", "r1"]
        r2 = body["items"][3]
        assert r2["workflow_id"] == "wf-a"
        assert Decimal(r2["total_cost_usd"]) == Decimal("3.00")
        assert r2["total_cost_display"] == "$3.00"
        assert r2["verdict"] == "FAIL"
        assert r2["score"] == 0.0
        assert r2["evidence_excerpt"] == "## FAIL\n\nchecked r2"
        assert r2["scorer"] == "eval_suite.py"
        assert r2["scored_at"] is not None
        # The version each run launched from, not the template's current one:
        # r2 started from 2.0.0 between runs of 1.0.0.
        assert r2["workflow_version"] == "2.0.0"
        assert body["items"][4]["workflow_version"] == "1.0.0"
        unscored = body["items"][0]
        assert (unscored["verdict"], unscored["score"], unscored["scorer"]) == (None, None, None)

    async def test_a_unique_prefix_of_the_eval_id_lists_its_runs(
        self, client: AsyncClient, lane2: _Lane2
    ) -> None:
        eval_id = await _two_by_two(client, lane2)

        body = (await client.get(f"/evals/{eval_id[:12]}/runs")).json()

        assert body["total"] == 5
        assert body["items"][0]["execution_id"] == "r5"

    async def test_an_eval_id_matching_no_eval_is_404(
        self, client: AsyncClient, lane2: _Lane2
    ) -> None:
        await _two_by_two(client, lane2)

        response = await client.get("/evals/eval-0000000000000000/runs")

        assert response.status_code == 404, response.text

    async def test_total_is_invariant_under_page_size(
        self, client: AsyncClient, lane2: _Lane2
    ) -> None:
        eval_id = await _two_by_two(client, lane2)

        pages = [
            (await client.get(f"/evals/{eval_id}/runs", params={"page": p, "page_size": 2})).json()
            for p in (1, 2, 3)
        ]
        whole = (await client.get(f"/evals/{eval_id}/runs", params={"page_size": 50})).json()

        assert {page["total"] for page in pages} == {5}
        assert whole["total"] == 5
        paged = [row["execution_id"] for page in pages for row in page["items"]]
        assert paged == [row["execution_id"] for row in whole["items"]]


class TestDelegation:
    async def test_a_delegate_s_model_is_part_of_the_run_and_its_variant(
        self, client: AsyncClient, lane2: _Lane2
    ) -> None:
        """A phase led by one model that delegated to another RAN both.

        Grouping it with a run that used only the leader would pool two
        different treatments, so the delegate's model (from the phase's cost
        split) is in the run's models and in its variant.
        """
        eval_id = await _create(client)
        await _run(lane2, eval_id, "solo", "wf-a", OPUS, "1", "2026-10-01T00:00:00+00:00")
        await _run(lane2, eval_id, "led", "wf-a", OPUS, "2", "2026-10-02T00:00:00+00:00")
        lane2.by_phase["led"] = {
            "verify": {
                OPUS: Decimal("1.5"),
                SONNET: Decimal("0.5"),
                UNKNOWN_MODEL_KEY: Decimal("0.1"),
            }
        }
        await _catch_up()

        runs = {
            r["execution_id"]: r
            for r in (await client.get(f"/evals/{eval_id}/runs")).json()["items"]
        }
        shown = (await client.get(f"/evals/{eval_id}")).json()

        assert runs["led"]["models"] == [
            {"phase_id": "verify", "model": OPUS},
            {"phase_id": "verify", "model": SONNET},
        ]
        assert runs["solo"]["models"] == [{"phase_id": "verify", "model": OPUS}]
        assert sorted(tuple(v["models"]) for v in shown["variants"]) == [
            (OPUS,),
            tuple(sorted((OPUS, SONNET))),
        ]

    async def test_an_unpriced_leader_is_not_dropped_by_a_priced_delegate(
        self, client: AsyncClient, lane2: _Lane2
    ) -> None:
        """The cost split holds only priced rows: the leader's own model must not depend on it."""
        eval_id = await _create(client)
        await _run(lane2, eval_id, "led", "wf-a", OPUS, "2", "2026-10-02T00:00:00+00:00")
        lane2.by_phase["led"] = {"verify": {SONNET: Decimal("0.5")}}
        await _catch_up()

        [run] = (await client.get(f"/evals/{eval_id}/runs")).json()["items"]

        assert run["models"] == [
            {"phase_id": "verify", "model": OPUS},
            {"phase_id": "verify", "model": SONNET},
        ]


class TestSummary:
    async def test_variants_and_pass_rate_over_two_workflows_by_two_models(
        self, client: AsyncClient, lane2: _Lane2
    ) -> None:
        eval_id = await _two_by_two(client, lane2)

        listed = (await client.get("/evals", params={"tag": "suite:verifier-seed"})).json()
        shown = (await client.get(f"/evals/{eval_id}")).json()

        [row] = listed["evals"]
        for body in (row, shown):
            assert body["run_count"] == 5
            assert body["scored_count"] == 4
            # r4's ERROR is scored but not judged: PASS over PASS + FAIL is 2/3.
            assert body["pass_rate"] == pytest.approx(2 / 3)
            assert body["pass_rate_display"] == "67%"
            assert body["last_run_at"] == "2026-10-05T00:00:00+00:00"
            assert body["last_verdict"] == "ERROR"
            variants = {
                (v["workflow_id"], v["workflow_version"], tuple(v["models"])): v
                for v in body["variants"]
            }
            # r2 ran wf-a 2.0.0: a different treatment from r1's 1.0.0, so its own variant.
            assert set(variants) == {
                ("wf-a", "1.0.0", (OPUS,)),
                ("wf-a", "2.0.0", (OPUS,)),
                ("wf-a", "1.0.0", (SONNET,)),
                ("wf-b", "1.0.0", (OPUS,)),
                ("wf-b", "1.0.0", (SONNET,)),
            }
            v1_opus = variants["wf-a", "1.0.0", (OPUS,)]
            assert (v1_opus["run_count"], v1_opus["pass_count"]) == (1, 1)
            assert v1_opus["pass_rate"] == pytest.approx(1.0)
            assert Decimal(v1_opus["avg_cost_usd"]) == Decimal("1.00")
            assert v1_opus["avg_cost_display"] == "$1.00"
            assert v1_opus["last_run_at"] == "2026-10-01T00:00:00+00:00"
            v2_opus = variants["wf-a", "2.0.0", (OPUS,)]
            assert (v2_opus["run_count"], v2_opus["pass_count"]) == (1, 0)
            assert v2_opus["pass_rate"] == pytest.approx(0.0)
            assert Decimal(v2_opus["avg_cost_usd"]) == Decimal("3.00")
            assert variants["wf-b", "1.0.0", (SONNET,)]["pass_rate"] is None
            assert variants["wf-b", "1.0.0", (SONNET,)]["pass_rate_display"] == "—"
            # ERROR-only: nothing was judged, so no rate rather than 0%.
            assert variants["wf-b", "1.0.0", (OPUS,)]["pass_count"] == 0
            assert variants["wf-b", "1.0.0", (OPUS,)]["pass_rate"] is None
            assert variants["wf-b", "1.0.0", (OPUS,)]["last_verdict"] == "ERROR"
            assert v1_opus["stats"]["median_cost_display"] == "$1.00"
            assert v1_opus["stats"]["cost_per_pass_display"] == "$1.00"
            assert v2_opus["stats"]["cost_per_pass_display"] == "—"

    async def test_eval_figures_cover_every_run_not_one_page_of_runs(
        self, client: AsyncClient, lane2: _Lane2
    ) -> None:
        """The detail's aggregates are the eval's, whatever page of runs the page shows."""
        eval_id = await _two_by_two(client, lane2)

        page = (await client.get(f"/evals/{eval_id}/runs", params={"page_size": 1})).json()
        shown = (await client.get(f"/evals/{eval_id}")).json()

        assert (len(page["items"]), page["total"]) == (1, 5)
        assert sum(v["run_count"] for v in shown["variants"]) == 5
        # Costs 1.00, 3.00, 0.50, 2.00, 0.25: median 1.00 over every run. Cost per
        # PASS is the SCORED spend 6.50 (ERROR's 2.00 in, unscored r5's 0.25 out)
        # over two PASS runs.
        assert shown["stats"]["median_cost_display"] == "$1.00"
        assert Decimal(shown["stats"]["cost_per_pass_usd"]) == Decimal("3.25")
        assert shown["stats"]["cost_per_pass_display"] == "$3.25"

    async def test_a_lower_bound_is_never_shown_as_a_whole_cost_or_duration(
        self, client: AsyncClient, lane2: _Lane2
    ) -> None:
        """r1 (PASS, $1.00) had an unpriced observation and a phase of unknown
        duration, so both its figures are lower bounds (#890). They must say so
        on the run, stay out of the medians, and make cost per PASS partial."""
        lane2.unpriced["r1"] = 1
        eval_id = await _two_by_two(client, lane2)
        await _complete_with_an_unmeasured_phase("r1", verify_seconds=300.0)

        runs = (await client.get(f"/evals/{eval_id}/runs")).json()["items"]
        shown = (await client.get(f"/evals/{eval_id}")).json()

        r1 = next(r for r in runs if r["execution_id"] == "r1")
        assert r1["total_cost_display"] == ">=$1.00 (partial)"
        # The real get_detail folded 300s known + one unmeasured phase.
        assert r1["duration_seconds"] == 300.0
        assert r1["duration_display"] == ">=5m (partial)"
        # The four complete costs 3.00, 0.50, 2.00, 0.25: median 1.25, not 1.00.
        assert Decimal(shown["stats"]["median_cost_usd"]) == Decimal("1.25")
        assert shown["stats"]["median_cost_display"] == "$1.25 (excl. 1 incomplete)"
        assert shown["stats"]["incomplete_duration_count"] == 1
        # The other four are still running, so their live durations are the median.
        assert shown["stats"]["median_duration_display"].endswith(" (excl. 1 incomplete)")
        assert shown["stats"]["cost_per_pass_display"] == ">=$3.25 (partial)"
        [v1_opus] = [
            v
            for v in shown["variants"]
            if (v["workflow_id"], v["workflow_version"], v["models"]) == ("wf-a", "1.0.0", [OPUS])
        ]
        # Its only run is a lower bound: no median to show, and it cannot win on cost.
        assert v1_opus["stats"]["median_cost_usd"] is None
        assert v1_opus["avg_cost_usd"] is None
        assert v1_opus["stats"]["cost_per_pass_display"] == ">=$1.00 (partial)"
        assert v1_opus["stats"]["incomplete_duration_count"] == 1
        assert v1_opus["stats"]["median_duration_seconds"] is None


class TestScore:
    async def test_rescoring_replaces_the_current_score(
        self, client: AsyncClient, lane2: _Lane2
    ) -> None:
        eval_id = await _two_by_two(client, lane2)

        response = await _score(client, eval_id, "r2", "PASS")
        await _catch_up()

        assert response.status_code == 200, response.text
        receipt = response.json()
        assert (receipt["execution_id"], receipt["verdict"], receipt["score"]) == (
            "r2",
            "PASS",
            1.0,
        )
        runs = (await client.get(f"/evals/{eval_id}/runs")).json()["items"]
        assert next(r for r in runs if r["execution_id"] == "r2")["verdict"] == "PASS"
        shown = (await client.get(f"/evals/{eval_id}")).json()
        assert shown["pass_rate"] == pytest.approx(3 / 3)

    async def test_a_non_member_cannot_be_scored(self, client: AsyncClient, lane2: _Lane2) -> None:
        eval_id = await _create(client)
        other = await _create(client)
        await _run(lane2, other, "elsewhere", "wf-a", OPUS, "1", "2026-10-01T00:00:00+00:00")
        await _run(lane2, None, "ordinary", "wf-a", OPUS, "1", "2026-10-01T00:00:00+00:00")

        refused = [
            await _score(client, eval_id, "elsewhere", "PASS"),
            await _score(client, eval_id, "ordinary", "PASS"),
            await _score(client, eval_id, "no-such-run", "PASS"),
        ]

        assert [r.status_code for r in refused] == [409, 409, 409]
        assert (await _score(client, "eval-missing", "elsewhere", "PASS")).status_code == 409

    async def test_an_unknown_eval_is_404_for_a_member_run(
        self, client: AsyncClient, lane2: _Lane2
    ) -> None:
        response = await _score(client, "eval-missing", "anything", "PASS")

        assert response.status_code in (404, 409)

    async def test_a_bad_verdict_is_422(self, client: AsyncClient, lane2: _Lane2) -> None:
        eval_id = await _create(client)

        response = await _score(client, eval_id, "r1", "MAYBE")

        assert response.status_code == 422


class TestExecutionDetailCarriesItsEval:
    """``GET /executions/{id}``'s ``eval``: the badge on the execution page."""

    async def test_a_scored_run_names_its_eval_and_current_verdict(
        self, client: AsyncClient, lane2: _Lane2
    ) -> None:
        eval_id = await _two_by_two(client, lane2)

        shown = (await client.get("/executions/r2")).json()["eval"]

        assert shown["eval_id"] == eval_id
        assert shown["eval_name"] == "verifier-seed: case-1"
        assert shown["association_kind"] == "launched"
        assert (shown["verdict"], shown["score"]) == ("FAIL", 0.0)
        assert shown["scored_at"] is not None

    async def test_a_rescore_moves_the_badge(self, client: AsyncClient, lane2: _Lane2) -> None:
        eval_id = await _two_by_two(client, lane2)

        assert (await _score(client, eval_id, "r2", "PASS")).status_code == 200
        await _catch_up()

        assert (await client.get("/executions/r2")).json()["eval"]["verdict"] == "PASS"

    async def test_an_unscored_run_has_its_eval_and_no_verdict(
        self, client: AsyncClient, lane2: _Lane2
    ) -> None:
        eval_id = await _two_by_two(client, lane2)

        shown = (await client.get("/executions/r5")).json()["eval"]

        assert (shown["eval_id"], shown["verdict"], shown["scored_at"]) == (eval_id, None, None)

    async def test_a_run_in_no_eval_has_none(self, client: AsyncClient, lane2: _Lane2) -> None:
        await _run(lane2, None, "ordinary", "wf-a", OPUS, "1", "2026-10-01T00:00:00+00:00")

        response = await client.get("/executions/ordinary")

        assert response.status_code == 200, response.text
        assert response.json()["eval"] is None

    async def test_a_detached_run_loses_the_badge(self, client: AsyncClient, lane2: _Lane2) -> None:
        eval_id = await _two_by_two(client, lane2)

        detached = await client.delete("/executions/r2/eval", params={"eval_id": eval_id})
        await _project_executions()

        assert detached.status_code == 200, detached.text
        assert (await client.get("/executions/r2")).json()["eval"] is None


class TestExecutionListCarriesItsEval:
    """``GET /executions``'s ``eval``: the badge on each row of the execution list."""

    async def _evals(self, client: AsyncClient) -> dict[str, ExecutionEvalRunResponse | None]:
        """Each listed execution's ``eval``, read back through the response model."""
        response = await client.get("/executions")
        assert response.status_code == 200, response.text
        listed = ExecutionListResponse.model_validate(response.json())
        return {row.workflow_execution_id: row.eval for row in listed.executions}

    async def test_each_row_carries_its_eval_and_verdict_and_an_ordinary_run_none(
        self, client: AsyncClient, lane2: _Lane2
    ) -> None:
        eval_id = await _two_by_two(client, lane2)
        await _run(lane2, None, "ordinary", "wf-a", OPUS, "1", "2026-10-06T00:00:00+00:00")

        evals = await self._evals(client)

        assert evals["ordinary"] is None
        detail = (await client.get("/executions/r2")).json()["eval"]
        assert evals["r2"] == ExecutionEvalRunResponse.model_validate(detail)
        verdicts = {key: run.verdict for key, run in evals.items() if run is not None}
        assert verdicts == {"r1": "PASS", "r2": "FAIL", "r3": "PASS", "r4": "ERROR", "r5": None}
        assert {run.eval_name for run in evals.values() if run is not None} == {
            "verifier-seed: case-1"
        }
        r5 = evals["r5"]
        assert r5 is not None and r5.eval_id == eval_id

    async def test_a_score_from_an_eval_the_run_left_is_not_its_verdict(
        self, client: AsyncClient, lane2: _Lane2
    ) -> None:
        first = await _two_by_two(client, lane2)
        created = await client.post("/evals", json={"name": "second", "goal": "Another goal"})
        assert created.status_code == 201, created.text
        second = created.json()["eval_id"]

        assert (await client.delete("/executions/r2/eval", params={"eval_id": first})).is_success
        assert (await client.post("/executions/r2/eval", json={"eval_id": second})).is_success
        await _project_executions()
        await _catch_up()

        shown = (await self._evals(client))["r2"]

        assert shown == ExecutionEvalRunResponse(
            eval_id=second,
            eval_name="second",
            association_kind="attached",
            verdict=None,
            score=None,
            scored_at=None,
        )

    async def test_in_eval_keeps_eval_runs_or_everything_else(
        self, client: AsyncClient, lane2: _Lane2
    ) -> None:
        await _two_by_two(client, lane2)
        await _run(lane2, None, "ordinary", "wf-a", OPUS, "1", "2026-10-06T00:00:00+00:00")

        evals_only = await client.get("/executions", params={"in_eval": "true"})
        hide_evals = await client.get("/executions", params={"in_eval": "false"})

        assert sorted(r["workflow_execution_id"] for r in evals_only.json()["executions"]) == [
            "r1",
            "r2",
            "r3",
            "r4",
            "r5",
        ]
        assert evals_only.json()["total"] == 5
        assert [r["workflow_execution_id"] for r in hide_evals.json()["executions"]] == ["ordinary"]
        assert hide_evals.json()["total"] == 1
        assert len(await self._evals(client)) == 6

    async def test_a_page_of_eval_runs_reads_the_eval_model_twice_not_per_row(
        self, client: AsyncClient, lane2: _Lane2, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from syn_adapters.projections.manager import get_projection_manager

        await _two_by_two(client, lane2)
        store = get_projection_manager().store
        reads: list[str] = []
        real_get, real_query = store.get, store.query

        async def get(projection: str, key: str):
            reads.append(projection)
            return await real_get(projection, key)

        async def query(projection: str, *args, **kwargs):
            reads.append(projection)
            return await real_query(projection, *args, **kwargs)

        monkeypatch.setattr(store, "get", get)
        monkeypatch.setattr(store, "query", query)

        evals = await self._evals(client)

        assert len([run for run in evals.values() if run is not None]) == 5
        assert sorted(r for r in reads if r in ("evals", "eval_run_scores")) == [
            "eval_run_scores",
            "evals",
        ]


async def _start_resumed_child(
    parent_id: str, child_id: str, *, workflow_version: str | None, reinstall_at: str | None
) -> None:
    """A parent that ran at ``workflow_version`` and failed, then the child its
    resume admitted - started through the same ``resume_start_command`` the
    resume route uses, AFTER the template was reinstalled at ``reinstall_at``."""
    from syn_api._wiring import get_workflow_execution_repository, get_workflow_repository
    from syn_domain.contexts.orchestration import (
        CreateWorkflowTemplateCommand,
        UpdateWorkflowTemplateCommand,
        WorkflowTemplateAggregate,
    )
    from syn_domain.contexts.orchestration.domain.aggregate_execution.commands import (
        FailExecutionCommand,
        ResumeExecutionCommand,
    )
    from syn_domain.contexts.orchestration.domain.aggregate_execution.start_pins import (
        phase_definitions_of,
    )
    from syn_domain.contexts.orchestration.domain.aggregate_execution.test_resume_start import (
        COMMIT,
        _pinned,
        _run_research,
    )
    from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
        FailureClassification,
    )
    from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.value_objects import (
        PhaseDefinition,
        WorkflowClassification,
        WorkflowType,
    )

    templates = get_workflow_repository()
    created = CreateWorkflowTemplateCommand(
        aggregate_id="wf-1",
        name="Resume provenance",
        workflow_type=WorkflowType.RESEARCH,
        classification=WorkflowClassification.SIMPLE,
        repository_url="",
        requires_repos=False,
        phases=[PhaseDefinition(phase_id="research", name="Research", order=1)],
        version=workflow_version,
    )
    template = WorkflowTemplateAggregate()
    template._handle_command(created)
    await templates.save(template)

    executions = get_workflow_execution_repository()
    phases = _pinned()
    parent = WorkflowExecutionAggregate()
    parent.start_execution(
        StartExecutionCommand(
            execution_id=parent_id,
            workflow_id="wf-1",
            workflow_name="Resume provenance",
            total_phases=len(phases),
            inputs={},
            phase_definitions=phase_definitions_of(phases),
            pinned_phases=phases,
            source_commits=[COMMIT],
            workflow_version=workflow_version,
        )
    )
    _run_research(parent)
    parent.fail_execution(
        FailExecutionCommand(
            execution_id=parent_id,
            error="boom",
            error_type="AgentError",
            failed_phase_id=None,
            completed_phases=1,
            total_phases=len(phases),
            classification=FailureClassification.UNCLASSIFIED,
        )
    )
    parent.resume_execution(
        ResumeExecutionCommand(execution_id=parent_id, resume_execution_id=child_id)
    )
    await executions.save_new(parent)

    if reinstall_at is not None:
        reinstalled = await templates.get_by_id("wf-1")
        assert reinstalled is not None
        reinstalled._handle_command(
            UpdateWorkflowTemplateCommand(
                **created.model_dump(exclude={"force", "version", "source_digest"}),
                version=reinstall_at,
                force=True,
            )
        )
        await templates.save(reinstalled)
        moved = await templates.get_by_id("wf-1")
        assert moved is not None
        assert moved.package_version == reinstall_at

    stored = await executions.get_by_id(parent_id)
    assert stored is not None
    child = WorkflowExecutionAggregate()
    child.start_resume(stored.resume_start_command())
    await executions.save_new(child)


async def _project_executions() -> None:
    from event_sourcing.stores.memory_checkpoint import MemoryCheckpointStore

    from syn_adapters.projections.manager import get_projection_manager
    from syn_adapters.storage.event_store_client import get_event_store_client
    from syn_domain.testing.stored_replay import replay

    await replay(
        get_event_store_client(),  # type: ignore[arg-type]  # memory client in tests
        MemoryCheckpointStore(),
        get_projection_manager().workflow_execution_list,
    )


class TestAResumedRunsVersion:
    """A resumed child is a run of the version its PARENT ran, whatever the
    template says by the time the child starts (Evals v2 provenance)."""

    async def test_a_template_reinstalled_between_parent_and_child_does_not_move_it(
        self, client: AsyncClient
    ) -> None:
        await _start_resumed_child(
            "exec-parent", "exec-child", workflow_version="1.2.3", reinstall_at="2.0.0"
        )
        eval_id = await _create(client)
        attached = await client.post("/executions/exec-child/eval", json={"eval_id": eval_id})
        assert attached.status_code == 200, attached.text
        await _project_executions()
        await _catch_up()

        runs = (await client.get(f"/evals/{eval_id}/runs")).json()["items"]

        assert [(r["execution_id"], r["workflow_version"]) for r in runs] == [
            ("exec-child", "1.2.3")
        ]

    async def test_a_parent_with_no_known_version_reports_none(self, client: AsyncClient) -> None:
        await _start_resumed_child(
            "exec-parent", "exec-child", workflow_version=None, reinstall_at="2.0.0"
        )
        eval_id = await _create(client)
        attached = await client.post("/executions/exec-child/eval", json={"eval_id": eval_id})
        assert attached.status_code == 200, attached.text
        await _project_executions()
        await _catch_up()

        runs = (await client.get(f"/evals/{eval_id}/runs")).json()["items"]

        assert [(r["execution_id"], r["workflow_version"]) for r in runs] == [("exec-child", None)]
