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
from syn_domain.contexts.organization.domain.read_models.repo_cost import RepoCost

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


@dataclass
class _StubStore:
    """Projection store holding only the repo correlation; nothing else is read."""

    repo_of: dict[str, str]

    async def query(self, projection: str, filters: dict[str, list[str]]) -> list[dict[str, str]]:
        names = set(filters["repo_full_name"])
        return [
            {"execution_id": e, "repo_full_name": r} for e, r in self.repo_of.items() if r in names
        ]

    async def get(self, projection: str, key: str) -> None:
        return None


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
) -> None:
    import syn_adapters.projection_stores as projection_stores
    import syn_domain.contexts.organization as organization
    from syn_api import _wiring, prefix_resolver
    from syn_api.routes import repos, systems
    from syn_api.types import Ok

    store = _StubStore(repo_of)

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

        costs = [_priced(), _unpriced("exec-other-repo"), _token_priced()]
        repo_of = {"exec-priced": REPO, "exec-other-repo": OTHER_REPO, "exec-token-priced": REPO}
        _patch(monkeypatch, costs, repo_of)

        @dataclass
        class _ListAll:
            async def list_all(self, limit: int = 500) -> list[ExecutionCost]:
                return costs

        async def _connected() -> None:
            return None

        from syn_api import _wiring

        monkeypatch.setattr(insights, "ensure_connected", _connected)
        system = await get_system_cost_endpoint("sys-1")
        monkeypatch.setattr(_wiring, "get_execution_cost_query", lambda: _ListAll())
        overall = await get_global_cost_endpoint(system_id="sys-1")

        assert system.total_cost_usd == overall.total_cost_usd == "1.65"
        assert system.unpriced_observation_count == overall.unpriced_observation_count == 9
        assert system.total_cost_display == overall.total_cost_display
