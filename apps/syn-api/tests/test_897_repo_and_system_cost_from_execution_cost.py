"""Repo and system cost read money AND coverage from ``ExecutionCost`` (#897 slice C).

``/repos/{id}/cost`` summed vendor cost in Timescale, where ``SUM`` skips a NULL
and so drops work priced only from its tokens. ``/systems/{id}/cost`` summed
``RepoCost`` payloads. Neither carried how much could not be priced. Both now
roll up ``ExecutionCost`` rows through the same helper as ``/insights/cost``.

These go THROUGH the endpoint with only the stores and queries stubbed, so the
scoping, the rollup and the response construction stay under test together.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from decimal import Decimal

import pytest

from syn_api.types import RepoCostResponse, SystemCostResponse
from syn_domain.contexts.orchestration.domain.read_models.execution_cost import ExecutionCost
from syn_domain.contexts.orchestration.slices.execution_cost.query_service import (
    ExecutionCostQueryService,
)
from syn_domain.contexts.organization._shared.projection_names import REPO_CORRELATION
from syn_domain.contexts.organization.domain.read_models.repo_cost import RepoCost
from syn_domain.contexts.organization.slices.repo_correlation.projection import (
    RepoCorrelationProjection,
)

REPO = "acme/payments"
OTHER_REPO = "acme/ledger"
OUTSIDE_REPO = "acme/elsewhere"
PRICED_MODEL = "claude-sonnet-4-5"


def _unpriced(execution_id: str = "exec-unpriced", count: int = 9) -> ExecutionCost:
    """A codex run whose model has no rate: real tokens, no dollars."""
    return ExecutionCost(
        execution_id=execution_id,
        workflow_id="wf-codex",
        input_tokens=40,
        output_tokens=1_700,
        total_cost_usd=Decimal("0"),
        unpriced_observation_count=count,
    )


def _priced(execution_id: str = "exec-priced") -> ExecutionCost:
    return ExecutionCost(
        execution_id=execution_id,
        workflow_id="wf-claude",
        input_tokens=100,
        output_tokens=200,
        cache_read_tokens=1_000,
        total_cost_usd=Decimal("1.25"),
        cost_by_model={PRICED_MODEL: Decimal("1.25")},
    )


def _token_priced() -> ExecutionCost:
    """Recorded no vendor cost (NULL ``total_cost_usd`` in the summary), priced
    from its tokens by ``ExecutionCost``. The old Timescale ``SUM`` skipped it."""
    return ExecutionCost(
        execution_id="exec-token-priced",
        workflow_id="wf-claude",
        input_tokens=500,
        output_tokens=50,
        total_cost_usd=Decimal("0.40"),
        cost_by_model={PRICED_MODEL: Decimal("0.40")},
    )


@dataclass
class _StubCostQuery:
    """``ExecutionCostQueryService`` at the ``list_for_ids`` seam."""

    costs: list[ExecutionCost]

    async def list_for_ids(self, execution_ids: object) -> list[ExecutionCost]:
        wanted = set(execution_ids)  # type: ignore[call-overload]  # test double: any iterable of ids
        return [c for c in self.costs if c.execution_id in wanted]

    async def list_all(self, limit: int = 500) -> list[ExecutionCost]:
        """Every row, unscoped: present so an unfiltered read fails on its total."""
        return self.costs[:limit]


@dataclass
class _StubStore:
    """Projection store holding only the repo correlation; nothing else is read.

    Keyed and queried like the real one, so ``RepoCorrelationProjection`` can
    write into it. ``reverse`` returns query rows in the opposite order.
    """

    records: dict[tuple[str, str], dict[str, str]] = field(default_factory=dict)
    reverse: bool = False

    @classmethod
    def from_repo_of(cls, repo_of: dict[str, str]) -> _StubStore:
        return cls(
            {
                (REPO_CORRELATION, f"{e}:{r}"): {"execution_id": e, "repo_full_name": r}
                for e, r in repo_of.items()
            }
        )

    async def save(self, projection: str, key: str, data: dict[str, str]) -> None:
        self.records[(projection, key)] = data

    async def query(self, projection: str, filters: dict[str, list[str]]) -> list[dict[str, str]]:
        names = set(filters["repo_full_name"])
        rows = [
            r
            for (p, _), r in self.records.items()
            if p == projection and r["repo_full_name"] in names
        ]
        return rows[::-1] if self.reverse else rows

    async def get(self, projection: str, key: str) -> dict[str, str] | None:
        return self.records.get((projection, key))


@dataclass
class _Repo:
    full_name: str
    repo_id: str = "repo-1"


@dataclass
class _System:
    name: str = "Payments"
    organization_id: str = "org-1"


@dataclass
class _RepoProjection:
    repos: list[_Repo]

    async def list_all(self, system_id: str | None = None) -> list[_Repo]:
        return self.repos


@dataclass
class _SystemProjection:
    async def get(self, system_id: str) -> _System:
        return _System()


@dataclass
class _OldRepoCostProjection:
    """What the pre-#897 route read: a total with no coverage to carry."""

    async def get_cost(self, key: str) -> RepoCost:
        return RepoCost(repo_full_name=key)


@dataclass
class _Mgr:
    store: _StubStore
    repo_cost: _OldRepoCostProjection = field(default_factory=_OldRepoCostProjection)


def _patch(
    monkeypatch: pytest.MonkeyPatch,
    costs: list[ExecutionCost],
    repo_of: dict[str, str],
    system_repos: tuple[str, ...] = (REPO, OTHER_REPO),
    store: _StubStore | None = None,
) -> None:
    import syn_adapters.projection_stores as projection_stores
    import syn_domain.contexts.organization as organization
    from syn_api import _wiring, prefix_resolver
    from syn_api.routes import repos, systems
    from syn_api.types import Ok

    store = store or _StubStore.from_repo_of(repo_of)

    async def _connected() -> None:
        return None

    async def _resolve(store: object, kind: str, ident: str, label: str) -> str:
        return ident

    async def _get_repo(repo_id: str) -> Ok[_Repo]:
        return Ok(_Repo(full_name=REPO, repo_id=repo_id))

    monkeypatch.setattr(repos, "ensure_connected", _connected)
    monkeypatch.setattr(systems, "ensure_connected", _connected)
    monkeypatch.setattr(repos, "get_repo", _get_repo)
    monkeypatch.setattr(prefix_resolver, "resolve_or_raise", _resolve)
    monkeypatch.setattr(_wiring, "get_projection_mgr", lambda: _Mgr(store))
    monkeypatch.setattr(_wiring, "get_execution_cost_query", lambda: _StubCostQuery(costs))
    monkeypatch.setattr(projection_stores, "get_projection_store", lambda: store)
    monkeypatch.setattr(organization, "get_system_projection", lambda: _SystemProjection())
    monkeypatch.setattr(
        organization,
        "get_repo_projection",
        lambda: _RepoProjection([_Repo(full_name=n) for n in system_repos]),
    )


async def _repo_cost(
    monkeypatch: pytest.MonkeyPatch, costs: list[ExecutionCost]
) -> RepoCostResponse:
    from syn_api.routes.repos import get_repo_cost_endpoint

    _patch(monkeypatch, costs, {c.execution_id: REPO for c in costs})
    return await get_repo_cost_endpoint("repo-1")


async def _system_cost(
    monkeypatch: pytest.MonkeyPatch, costs: list[ExecutionCost]
) -> SystemCostResponse:
    from syn_api.routes.systems import get_system_cost_endpoint

    _patch(monkeypatch, costs, {c.execution_id: REPO for c in costs})
    return await get_system_cost_endpoint("sys-1")


_Endpoint = Callable[
    [pytest.MonkeyPatch, list[ExecutionCost]], Awaitable[RepoCostResponse | SystemCostResponse]
]

_ENDPOINTS = pytest.mark.parametrize("endpoint", [_repo_cost, _system_cost], ids=["repo", "system"])


@pytest.mark.unit
class TestRepoAndSystemCostFromExecutionCost:
    @pytest.mark.asyncio
    @_ENDPOINTS
    async def test_wholly_unpriced_is_unpriced_not_zero_dollars(
        self, monkeypatch: pytest.MonkeyPatch, endpoint: _Endpoint
    ) -> None:
        response = await endpoint(monkeypatch, [_unpriced()])

        assert response.unpriced_observation_count == 9
        assert response.total_cost_display == "unpriced"
        assert response.total_output_tokens == 1_700

    @pytest.mark.asyncio
    @_ENDPOINTS
    async def test_partly_priced_is_a_lower_bound(
        self, monkeypatch: pytest.MonkeyPatch, endpoint: _Endpoint
    ) -> None:
        response = await endpoint(monkeypatch, [_unpriced(), _priced()])

        assert response.total_cost_usd == "1.25"
        assert response.unpriced_observation_count == 9
        assert response.total_cost_display == ">=$1.25 (partial)"
        assert response.cost_by_workflow == {"wf-codex": "0", "wf-claude": "1.25"}
        assert response.cost_by_model == {PRICED_MODEL: "1.25"}
        assert response.total_tokens == 40 + 1_700 + 100 + 200 + 1_000
        assert response.execution_count == 2

    @pytest.mark.asyncio
    @_ENDPOINTS
    async def test_fully_priced_is_a_plain_total(
        self, monkeypatch: pytest.MonkeyPatch, endpoint: _Endpoint
    ) -> None:
        response = await endpoint(monkeypatch, [_priced()])

        assert response.unpriced_observation_count == 0
        assert response.total_cost_display == "$1.25"

    @pytest.mark.asyncio
    @_ENDPOINTS
    async def test_every_unpriced_execution_counts_not_just_the_last(
        self, monkeypatch: pytest.MonkeyPatch, endpoint: _Endpoint
    ) -> None:
        costs = [_unpriced(), _unpriced("exec-unpriced-2", count=4)]

        response = await endpoint(monkeypatch, costs)

        assert response.unpriced_observation_count == 13

    @pytest.mark.asyncio
    @_ENDPOINTS
    async def test_token_priced_work_with_no_vendor_cost_is_now_in_the_total(
        self, monkeypatch: pytest.MonkeyPatch, endpoint: _Endpoint
    ) -> None:
        """The intended behaviour change: the old sources dropped this execution."""
        response = await endpoint(monkeypatch, [_priced(), _token_priced()])

        assert response.total_cost_usd == "1.65"
        assert response.total_cost_display == "$1.65"

    @pytest.mark.asyncio
    async def test_an_execution_outside_the_repo_adds_neither_money_nor_coverage(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from syn_api.routes.repos import get_repo_cost_endpoint

        outsider = replace(_unpriced("exec-outside", count=50), total_cost_usd=Decimal("7"))
        _patch(
            monkeypatch,
            [_priced(), outsider],
            {"exec-priced": REPO, "exec-outside": OUTSIDE_REPO},
        )

        response = await get_repo_cost_endpoint("repo-1")

        assert response.repo_id == "repo-1"
        assert response.repo_full_name == REPO
        assert response.total_cost_usd == "1.25"
        assert response.unpriced_observation_count == 0
        assert response.execution_count == 1

    @pytest.mark.asyncio
    async def test_an_execution_outside_the_system_adds_neither_money_nor_coverage(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from syn_api.routes.systems import get_system_cost_endpoint

        outsider = replace(_unpriced("exec-outside", count=50), total_cost_usd=Decimal("7"))
        _patch(
            monkeypatch,
            [_priced(), _unpriced("exec-other-repo"), outsider],
            {"exec-priced": REPO, "exec-other-repo": OTHER_REPO, "exec-outside": OUTSIDE_REPO},
        )

        response = await get_system_cost_endpoint("sys-1")

        assert response.system_name == "Payments"
        assert response.organization_id == "org-1"
        assert response.total_cost_usd == "1.25"
        assert response.unpriced_observation_count == 9
        assert response.cost_by_repo == {REPO: "1.25", OTHER_REPO: "0"}
        assert response.execution_count == 2

    @pytest.mark.asyncio
    async def test_system_cost_agrees_with_insights_cost_for_the_system(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from syn_api.routes import insights
        from syn_api.routes.insights import get_global_cost_endpoint
        from syn_api.routes.systems import get_system_cost_endpoint

        outsider = replace(_unpriced("exec-outside", count=50), total_cost_usd=Decimal("7"))
        costs = [_priced(), _unpriced("exec-other-repo"), _token_priced(), outsider]
        repo_of = {
            "exec-priced": REPO,
            "exec-other-repo": OTHER_REPO,
            "exec-token-priced": REPO,
            "exec-outside": OUTSIDE_REPO,
        }
        _patch(monkeypatch, costs, repo_of)

        async def _connected() -> None:
            return None

        monkeypatch.setattr(insights, "ensure_connected", _connected)
        system = await get_system_cost_endpoint("sys-1")
        overall = await get_global_cost_endpoint(system_id="sys-1")

        assert system.total_cost_usd == overall.total_cost_usd == "1.65"
        assert system.unpriced_observation_count == overall.unpriced_observation_count == 9
        assert system.total_cost_display == overall.total_cost_display


def _converted(execution_id: str = "exec-priced") -> ExecutionCost:
    """Built by the production token-usage converter, which reads no workflow id."""
    row = {
        "execution_id": execution_id,
        "model": PRICED_MODEL,
        "requested_model": "sonnet",
        "has_requested_model": True,
        "total_input": 1_000_000,
        "total_output": 0,
        "cache_creation": 0,
        "cache_read": 0,
        "session_ids": ["session-1"],
        "observation_count": 1,
        "started_at": None,
        "last_observation": None,
    }
    cost = ExecutionCostQueryService(object())._build_from_token_usage(execution_id, [row], {})  # type: ignore[arg-type]  # no pool: the converter does not touch it
    assert cost.workflow_id is None
    assert cost.total_cost_usd > 0
    return cost


async def _correlated_by_producer(*, reverse: bool = False) -> _StubStore:
    """One execution correlated with two repos, written by the real producer.

    A trigger on ``REPO`` starts a workflow whose ``repository_url`` input names
    ``OTHER_REPO``: the projection keys each ``execution_id:repo`` separately.
    """
    store = _StubStore(reverse=reverse)
    projection = RepoCorrelationProjection(store)  # type: ignore[arg-type]  # test double implements the methods it calls
    await projection.on_trigger_fired(
        {"execution_id": "exec-priced", "workflow_id": "wf-claude", "repository": REPO}
    )
    await projection.on_workflow_execution_started(
        {
            "execution_id": "exec-priced",
            "workflow_id": "wf-claude",
            "inputs": {"repository_url": f"https://github.com/{OTHER_REPO}.git"},
        }
    )
    assert len(store.records) == 2
    return store


@pytest.mark.unit
class TestProductionShapedCostRows:
    """Rows and correlations as production writes them, not hand-built (verify round 1)."""

    @pytest.mark.asyncio
    async def test_workflow_comes_from_the_correlation_when_the_cost_row_has_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from syn_api.routes.repos import get_repo_cost_endpoint
        from syn_api.routes.systems import get_system_cost_endpoint

        cost = _converted()
        _patch(monkeypatch, [cost], {}, store=await _correlated_by_producer())

        repo = await get_repo_cost_endpoint("repo-1")
        system = await get_system_cost_endpoint("sys-1")

        assert repo.cost_by_workflow == {"wf-claude": str(cost.total_cost_usd)}
        assert system.cost_by_workflow == {"wf-claude": str(cost.total_cost_usd)}

    @pytest.mark.asyncio
    @pytest.mark.parametrize("reverse", [False, True], ids=["store-order", "reversed"])
    async def test_one_execution_in_two_repos_is_in_both_buckets_and_counted_once(
        self, monkeypatch: pytest.MonkeyPatch, reverse: bool
    ) -> None:
        from syn_api.routes.systems import get_system_cost_endpoint

        _patch(monkeypatch, [_priced()], {}, store=await _correlated_by_producer(reverse=reverse))

        response = await get_system_cost_endpoint("sys-1")

        assert response.cost_by_repo == {REPO: "1.25", OTHER_REPO: "1.25"}
        assert response.total_cost_usd == "1.25"
        assert response.execution_count == 1

    @pytest.mark.asyncio
    async def test_system_and_insights_agree_when_newer_work_elsewhere_fills_the_window(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``/insights/cost`` read the latest 10,000 executions, THEN filtered by system."""
        from syn_api.routes import insights
        from syn_api.routes.insights import get_global_cost_endpoint
        from syn_api.routes.systems import get_system_cost_endpoint

        newer_elsewhere = [_priced(f"exec-outside-{i}") for i in range(10_000)]
        _patch(monkeypatch, [*newer_elsewhere, _priced()], {"exec-priced": REPO})

        async def _connected() -> None:
            return None

        monkeypatch.setattr(insights, "ensure_connected", _connected)
        system = await get_system_cost_endpoint("sys-1")
        overall = await get_global_cost_endpoint(system_id="sys-1")

        assert system.total_cost_usd == overall.total_cost_usd == "1.25"
        assert system.execution_count == overall.execution_count == 1
