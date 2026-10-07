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
            execution_id=execution_id, total_cost_usd=cost, input_tokens=10, output_tokens=10
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
