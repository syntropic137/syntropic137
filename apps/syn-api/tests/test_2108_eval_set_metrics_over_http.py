"""#2108 S2: an eval set's trial figures over HTTP, computed by the domain and nowhere else.

Seeded straight into the read models the routes read, so each test pins what
the facts mapping (``RunReads.facts``) hands the domain: the run's launch tags
(``inherited_tags``, never the editable ``tags``), its failure classification,
its starting checkout against the eval's baseline, and its phases' images.
"""

from __future__ import annotations

import os

os.environ.setdefault("APP_ENVIRONMENT", "test")

from typing import TYPE_CHECKING

import pytest
from httpx import ASGITransport, AsyncClient

from syn_api.routes.executions.commands import ExecuteWorkflowRequest
from syn_api.types import EvalDetailResponse, EvalRunListResponse, EvalSetMetricsResponse
from syn_domain.contexts.agent_sessions.domain.read_models.session_cost import SessionCost
from syn_domain.contexts.orchestration.domain.aggregate_execution.ImageManifestValueObjects import (
    ImageManifestContent,
    ImageManifestReading,
    ImageManifestState,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    FailureClassification,
    SourceCommit,
)
from syn_domain.contexts.orchestration.domain.read_models.eval_runs import EvalRunScore
from syn_domain.contexts.orchestration.domain.read_models.eval_summary import (
    EvalBaselineRepo,
    EvalRecord,
)
from syn_domain.contexts.orchestration.domain.read_models.eval_trials import (
    declared_model_tags,
    models_digest,
)
from syn_domain.contexts.orchestration.domain.read_models.workflow_execution_detail import (
    PhaseExecutionDetail,
    WorkflowExecutionDetail,
)
from syn_domain.contexts.orchestration.domain.read_models.workflow_execution_summary import (
    WorkflowExecutionSummary,
)
from syn_domain.contexts.orchestration.slices.execution_cost.query_service import (
    ExecutionCostsForIds,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator, Sequence

pytestmark = [pytest.mark.unit, pytest.mark.anyio]

OPUS = "claude-opus-5-5"
REPO_OWNER, REPO_NAME = "syntropic137", "syntropic137"
PIN = "a" * 40
SUITE = "verifier-seed-v1"
MODELS = "m" * 32
PROTOCOL_A, PROTOCOL_B = "keyword-v1", "panel-v1"
_seq = iter(range(1_000_000))


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
    """Every session ran opus; no run has cost data."""

    async def get_session_costs(self, session_ids: Sequence[str]) -> dict[str, SessionCost]:
        return {
            sid: SessionCost(session_id=sid, agent_model=OPUS, requested_model=OPUS)
            for sid in session_ids
        }

    async def list_costs_for_ids(self, execution_ids: list[str]) -> ExecutionCostsForIds:
        return ExecutionCostsForIds(costs=[], tool_calls={})


@pytest.fixture
async def client(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[AsyncClient]:
    from syn_api._wiring import ensure_connected, get_projection_mgr
    from syn_api.main import create_app

    await ensure_connected()
    manager = get_projection_mgr()
    fake = _Lane2()
    monkeypatch.setattr(manager.session_cost, "get_session_costs", fake.get_session_costs)
    monkeypatch.setattr(manager.execution_cost, "list_costs_for_ids", fake.list_costs_for_ids)
    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://t") as c:
        yield c


def _launch_tags(scorer: str = PROTOCOL_A, version: str = "1") -> list[str]:
    return [f"suite:{SUITE}", f"suite-version:{version}", f"models:{MODELS}", f"scorer:{scorer}"]


async def _eval(eval_id: str, *tags: str) -> None:
    from syn_api._wiring import get_projection_mgr

    record = EvalRecord(
        eval_id=eval_id,
        name=eval_id,
        goal="g",
        baseline_repos=(
            EvalBaselineRepo(
                owner=REPO_OWNER, name=REPO_NAME, requested_ref="main", commit_sha=PIN
            ),
        ),
        tags=(f"suite:{SUITE}", *tags),
        frozen=True,
        created_at="2026-10-27T00:00:00Z",
    )
    await get_projection_mgr().store.save("evals", eval_id, record.model_dump(mode="json"))


def _image(build_commit: str) -> ImageManifestReading:
    return ImageManifestReading(
        state=ImageManifestState.READ,
        manifest=ImageManifestContent(
            provider="claude",
            provider_version="2.1.0",
            components={"node": "22"},
            build_commit=build_commit,
            built_at="2026-10-27T00:00:00Z",
            manifest_digest="d" * 64,
        ),
    )


async def _run(
    eval_id: str,
    *,
    status: str = "completed",
    verdict: str | None = "PASS",
    scorer: str = PROTOCOL_A,
    inherited: list[str] | None = None,
    tags: list[str] | None = None,
    classification: FailureClassification = FailureClassification.UNCLASSIFIED,
    checkout_sha: str | None = PIN,
    image: ImageManifestReading | None = None,
) -> str:
    """One launched run of ``eval_id``, written into every read model a run is read from."""
    from syn_api._wiring import get_projection_mgr

    store = get_projection_mgr().store
    n = next(_seq)
    execution_id = f"exec-{n:04d}"
    started = f"2026-10-27T00:{n // 60:02d}:{n % 60:02d}+00:00"
    # Through the execute request's own TagSet, so no test holds a launch tag
    # a real launch would refuse (codex #2123: `=` and a 71-char tag did).
    raw = _launch_tags(scorer) if inherited is None else inherited
    launch = list(ExecuteWorkflowRequest(tags=raw).tags)
    summary = WorkflowExecutionSummary(
        workflow_execution_id=execution_id,
        workflow_id="verify-v1",
        workflow_name="verify",
        status=status,
        started_at=started,
        completed_at=None,
        completed_phases=1,
        total_phases=1,
        total_tokens=0,
        eval_id=eval_id,
        association_kind="launched",
        workflow_version="v1",
        failure_classification=classification,
        tags=tuple(launch if tags is None else tags),
        inherited_tags=tuple(launch),
    )
    await store.save("workflow_executions", execution_id, summary.to_dict())
    detail = WorkflowExecutionDetail(
        workflow_execution_id=execution_id,
        workflow_id="verify-v1",
        workflow_name="verify",
        status=status,
        started_at=started,
        phases=(
            PhaseExecutionDetail(
                workflow_phase_id="verify",
                name="verify",
                status=status,
                session_id=f"sess-{execution_id}",
                image_manifest=image or _image("c1"),
            ),
        ),
        starting_checkout=()
        if checkout_sha is None
        else (SourceCommit(repository=f"{REPO_OWNER}/{REPO_NAME}", sha=checkout_sha),),
    )
    await store.save("workflow_execution_details", execution_id, detail.to_dict())
    if verdict is not None:
        score = EvalRunScore(
            eval_id=eval_id,
            execution_id=execution_id,
            verdict=verdict,  # pyright: ignore[reportArgumentType]  # str coerced to Verdict
            scorer="eval_suite.py",
            scorer_version=scorer,
            scored_at=started,
        )
        await store.save(
            "eval_run_scores", f"{eval_id}/{execution_id}", score.model_dump(mode="json")
        )
    return execution_id


async def _metrics(client: AsyncClient, **params: str | int) -> EvalSetMetricsResponse:
    response = await client.get(
        "/eval-sets/metrics", params={"suite": SUITE, "version": "1", **params}
    )
    assert response.status_code == 200, response.text
    return EvalSetMetricsResponse.model_validate(response.json())


async def test_an_infra_trial_is_counted_as_infra_and_lowers_only_the_lower_bound(
    client: AsyncClient,
) -> None:
    await _eval("eval-a", "suite-version:1")
    await _run("eval-a")
    await _run("eval-a")
    # The platform broke: not a fail, whatever was scored.
    await _run(
        "eval-a",
        status="failed",
        verdict="FAIL",
        classification=FailureClassification.PLATFORM,
    )

    body = await _metrics(client, k=2)

    (block,) = body.cohorts
    (case,) = block.cases
    assert (case.n, case.c, case.infra_error_count) == (2, 2, 1)
    assert case.pass_hat_k == 1.0
    # Infra as a fail: n = 3, c = 2, so pass^2 = C(2,2) / C(3,2) = 1/3.
    assert case.pass_hat_k_bounds.lower == pytest.approx(1 / 3)
    assert case.pass_hat_k_bounds.upper == 1.0
    assert block.infra_error_count == 1
    assert block.pass_hat_k_bounds.lower == pytest.approx(1 / 3)
    assert body.isolation == "unproven"


async def test_a_trial_is_read_from_its_launch_tags_not_its_edited_ones(
    client: AsyncClient,
) -> None:
    """T1b: the facts mapping reads ``inherited_tags``; a retag of ``tags`` moves nothing."""
    await _eval("eval-a", "suite-version:1")
    await _run("eval-a", tags=_launch_tags(PROTOCOL_B))  # retagged, still a protocol-A trial
    await _run("eval-a", inherited=[], tags=_launch_tags())  # cohort only in edited tags

    body = await _metrics(client, k=1)

    assert [c.cohort.scorer_protocol for c in body.cohorts] == [PROTOCOL_A]
    assert body.cohorts[0].cases[0].n == 1
    assert body.not_a_trial_count == 1


async def test_a_run_started_off_the_baseline_is_excluded_and_counted(
    client: AsyncClient,
) -> None:
    await _eval("eval-a", "suite-version:1")
    await _run("eval-a")
    await _run("eval-a", checkout_sha="b" * 40)

    body = await _metrics(client, k=1)

    case = body.cohorts[0].cases[0]
    assert (case.n, case.base_mismatch_count) == (1, 1)


async def test_the_roster_is_the_version_and_split_asked_for(client: AsyncClient) -> None:
    await _eval("eval-a", "suite-version:1", "split:holdout", "polarity:defect")
    await _eval("eval-b", "suite-version:1", "split:train", "polarity:clean")
    await _eval("eval-c", "suite-version:2", "split:holdout")
    await _run("eval-a")

    everything = await _metrics(client, k=1)
    holdout = await _metrics(client, k=1, split="holdout")

    assert [(c.eval_id, c.split, c.polarity) for c in everything.roster] == [
        ("eval-a", "holdout", "defect"),
        ("eval-b", "train", "clean"),
    ]
    assert everything.cohorts[0].coverage.never_launched == 1
    assert everything.cohorts[0].partial is True
    assert [c.eval_id for c in holdout.roster] == ["eval-a"]
    assert holdout.cohorts[0].partial is False


async def test_two_cohorts_on_one_roster_are_compared(client: AsyncClient) -> None:
    await _eval("eval-a", "suite-version:1")
    await _eval("eval-b", "suite-version:1")
    for eval_id in ("eval-a", "eval-b"):
        await _run(eval_id, image=_image("c1"))
        await _run(eval_id, verdict="FAIL", scorer=PROTOCOL_B, image=_image("c2"))

    body = await _metrics(client, k=1)

    assert [c.cohort.scorer_protocol for c in body.cohorts] == [PROTOCOL_A, PROTOCOL_B]
    assert [[m.build_commit for m in c.image_manifests] for c in body.cohorts] == [["c1"], ["c2"]]
    pair = body.comparison
    assert pair is not None
    assert (pair.a_only, pair.b_only, pair.coverage_complete) == (2, 0, True)
    assert pair.difference is not None
    assert pair.difference.estimate == 1.0


async def test_one_cohort_has_no_comparison_and_an_unknown_suite_is_empty(
    client: AsyncClient,
) -> None:
    await _eval("eval-a", "suite-version:1")
    await _run("eval-a")

    body = await _metrics(client, k=1)
    unknown = await _metrics(client, k=1, suite="no-such-suite")

    assert body.comparison is None
    assert (unknown.roster, unknown.cohorts) == ([], [])


async def test_k_is_required_and_positive(client: AsyncClient) -> None:
    missing = await client.get("/eval-sets/metrics", params={"suite": SUITE, "version": "1"})
    zero = await client.get("/eval-sets/metrics", params={"suite": SUITE, "version": "1", "k": 0})

    assert (missing.status_code, zero.status_code) == (422, 422)


async def test_an_eval_reports_its_cohorts_when_asked_with_k(client: AsyncClient) -> None:
    await _eval("eval-a", "suite-version:1")
    await _run("eval-a")
    await _run("eval-a", status="failed", classification=FailureClassification.PLATFORM)

    plain = await client.get("/evals/eval-a")
    with_k = await client.get("/evals/eval-a", params={"k": 2})

    assert EvalDetailResponse.model_validate(plain.json()).cohorts is None
    cohorts = EvalDetailResponse.model_validate(with_k.json()).cohorts
    assert cohorts is not None
    (only,) = cohorts
    assert (only.metrics.n, only.metrics.infra_error_count, only.metrics.trials_short) == (
        1,
        1,
        1,
    )


async def test_each_run_row_says_what_it_counts_as(client: AsyncClient) -> None:
    await _eval("eval-a", "suite-version:1")
    passed = await _run("eval-a")
    infra = await _run("eval-a", status="failed", classification=FailureClassification.PLATFORM)
    refused = await _run(
        "eval-a", status="failed", classification=FailureClassification.CORRECT_REFUSAL
    )
    unscored = await _run("eval-a", verdict=None)
    off_base = await _run("eval-a", checkout_sha="b" * 40)
    untagged = await _run("eval-a", inherited=[])

    response = await client.get("/evals/eval-a/runs")

    assert response.status_code == 200, response.text
    rows = EvalRunListResponse.model_validate(response.json()).items
    assert {r.execution_id: r.trial_result for r in rows} == {
        passed: "pass",
        infra: "infra_error",
        refused: "fail",
        unscored: "pending",
        off_base: "base_mismatch",
        untagged: "not_a_trial",
    }


async def test_a_phase_that_ran_another_model_than_declared_is_excluded(
    client: AsyncClient,
) -> None:
    """The facts mapping hands the domain each phase's OWN observed model (Lane 2).

    Launch tags come from ``declared_model_tags``, the writer the harness uses,
    so the declared models are in the grammar a real launch accepts.
    """
    base = [f"suite:{SUITE}", "suite-version:1", f"scorer:{PROTOCOL_A}"]
    as_declared, swapped = {"verify": OPUS}, {"verify": "gpt-6.1-sol"}
    await _eval("eval-a", "suite-version:1")
    await _run("eval-a", inherited=[*base, *declared_model_tags(as_declared)])
    await _run("eval-a", inherited=[*base, *declared_model_tags(swapped)])

    body = await _metrics(client, k=1)

    by_models = {
        c.cohort.models_digest: (c.cases[0].n, c.cases[0].treatment_mismatch_count)
        for c in body.cohorts
    }
    assert by_models == {
        models_digest(as_declared): (1, 0),
        models_digest(swapped): (0, 1),
    }


async def test_a_roster_over_the_case_limit_is_refused_not_truncated(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from syn_api.routes import eval_sets

    monkeypatch.setattr(eval_sets, "MAX_EVAL_SET_CASES", 2)
    for eval_id in ("eval-a", "eval-b", "eval-c"):
        await _eval(eval_id, "suite-version:1")

    response = await client.get(
        "/eval-sets/metrics", params={"suite": SUITE, "version": "1", "k": 1}
    )

    assert response.status_code == 422
    assert "has 3, more than the 2" in response.json()["detail"]


async def test_a_set_over_the_run_limit_is_refused_before_its_runs_load(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from syn_api.routes import eval_sets

    monkeypatch.setattr(eval_sets, "MAX_EVAL_SET_RUNS", 2)
    loaded: list[int] = []

    async def _refuse_load(*_: object, **__: object) -> None:
        loaded.append(1)
        raise AssertionError("runs were loaded past the limit")

    monkeypatch.setattr(eval_sets.RunReads, "load", _refuse_load)
    await _eval("eval-a", "suite-version:1")
    await _eval("eval-b", "suite-version:1")
    for eval_id in ("eval-a", "eval-a", "eval-b"):
        await _run(eval_id)

    response = await client.get(
        "/eval-sets/metrics", params={"suite": SUITE, "version": "1", "k": 1}
    )

    assert response.status_code == 422
    assert "has 3, more than the 2" in response.json()["detail"]
    assert loaded == []


async def test_one_eval_over_the_run_limit_refuses_its_cohorts(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from syn_api.routes import eval_sets

    monkeypatch.setattr(eval_sets, "MAX_EVAL_SET_RUNS", 1)
    await _eval("eval-a", "suite-version:1")
    await _run("eval-a")
    await _run("eval-a")

    response = await client.get("/evals/eval-a", params={"k": 1})

    assert response.status_code == 422
    assert "eval eval-a has 2, more than the 1" in response.json()["detail"]
