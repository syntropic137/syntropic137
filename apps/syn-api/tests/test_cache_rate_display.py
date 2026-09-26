"""Cache rate labels come from the price table, not from a constant.

The dashboard hard-coded "0.1x rate" / "1.25x rate". Opus 5.5 reads cache at
$0.20 against $4 input, 0.05x; an execution that also ran GPT-6-Sol (0.1x) has
no single read rate at all. These cases drive both routes that serve the
labels, GET /executions/{id} and GET /sessions/{id}, through their endpoint
functions.
"""

from __future__ import annotations

import os
from decimal import Decimal

import pytest

from syn_api.cache_rate_display import cache_rate_display, format_rate_multiplier
from syn_api.types import ExecutionDetailFull, Ok, PhaseExecution, SessionDetail
from syn_shared.agents import ModelId
from syn_shared.observed_model import UNKNOWN_MODEL_KEY

pytestmark = pytest.mark.unit

os.environ.setdefault("APP_ENVIRONMENT", "test")

OPUS = str(ModelId.CLAUDE_OPUS_5_5)
SOL = str(ModelId.GPT_6_SOL)


# -- the helper ---------------------------------------------------------------


def test_opus_5_5_only() -> None:
    labels = cache_rate_display([OPUS])
    assert labels.cache_read_rate_display == "0.05x rate"
    assert labels.cache_write_rate_display == "1.25x rate"


def test_opus_and_sol_share_a_write_rate_but_not_a_read_rate() -> None:
    labels = cache_rate_display([OPUS, SOL])
    assert labels.cache_read_rate_display is None
    assert labels.cache_write_rate_display == "1.25x rate"


def test_sol_only_reads_at_a_tenth() -> None:
    assert cache_rate_display([SOL]).cache_read_rate_display == "0.1x rate"


@pytest.mark.parametrize("models", [["not-a-real-model"], [OPUS, UNKNOWN_MODEL_KEY], []])
def test_unknown_or_absent_models_have_no_label(models: list[str]) -> None:
    labels = cache_rate_display(models)
    assert labels.cache_read_rate_display is None
    assert labels.cache_write_rate_display is None


@pytest.mark.parametrize(
    ("multiplier", "expected"),
    [
        (Decimal("0.05"), "0.05x rate"),
        (Decimal("0.10"), "0.1x rate"),
        (Decimal("1.25"), "1.25x rate"),
        (Decimal("2.00"), "2x rate"),
        (Decimal("10"), "10x rate"),
        (Decimal(1) / Decimal(3), "0.3333x rate"),
    ],
)
def test_multiplier_formatting(multiplier: Decimal, expected: str) -> None:
    assert format_rate_multiplier(multiplier) == expected


# -- GET /executions/{id} -----------------------------------------------------


def _phase(phase_id: str, cost_by_model: dict[str, Decimal], model: str | None) -> PhaseExecution:
    return PhaseExecution(
        phase_id=phase_id,
        name=phase_id,
        status="completed",
        model=model,
        cost_by_model=cost_by_model,
    )


async def _execution_response(monkeypatch: pytest.MonkeyPatch, phases: list[PhaseExecution]):
    from syn_api import _wiring, prefix_resolver
    from syn_api.routes.executions import queries

    async def _resolve(_store: object, _kind: str, value: str, _label: str) -> str:
        return value

    async def _detail(execution_id: str):
        return Ok(
            ExecutionDetailFull(
                workflow_execution_id=execution_id,
                workflow_id="wf",
                workflow_name="wf",
                status="completed",
                phases=phases,
                total_duration_seconds=None,
                repos=[],
            )
        )

    class _Mgr:
        store = None

    monkeypatch.setattr(prefix_resolver, "resolve_or_raise", _resolve)
    monkeypatch.setattr(_wiring, "get_projection_mgr", _Mgr)
    monkeypatch.setattr(queries, "get_detail", _detail)
    return await queries.get_execution_endpoint("exec-1")


@pytest.mark.asyncio
async def test_execution_on_opus_5_5_reports_its_own_rates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = await _execution_response(
        monkeypatch, [_phase("plan", {OPUS: Decimal("0.3056678")}, OPUS)]
    )
    assert response.cache_read_rate_display == "0.05x rate"
    assert response.cache_write_rate_display == "1.25x rate"


@pytest.mark.asyncio
async def test_mixed_model_execution_blanks_only_the_rate_that_differs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = await _execution_response(
        monkeypatch,
        [
            _phase("plan", {OPUS: Decimal("0.3")}, OPUS),
            # Not yet priced: its reported model still counts.
            _phase("build", {}, SOL),
        ],
    )
    assert response.cache_read_rate_display is None
    assert response.cache_write_rate_display == "1.25x rate"


@pytest.mark.asyncio
async def test_unattributed_cost_blanks_the_labels(monkeypatch: pytest.MonkeyPatch) -> None:
    response = await _execution_response(
        monkeypatch,
        [_phase("plan", {OPUS: Decimal("0.3"), UNKNOWN_MODEL_KEY: Decimal("0.1")}, OPUS)],
    )
    assert response.cache_read_rate_display is None
    assert response.cache_write_rate_display is None


# -- GET /sessions/{id} -------------------------------------------------------


async def _session_response(monkeypatch: pytest.MonkeyPatch, detail: SessionDetail):
    from syn_api import prefix_resolver
    from syn_api.routes import sessions

    async def _resolve(_store: object, _kind: str, value: str, _label: str) -> str:
        return value

    async def _get_session(session_id: str):
        return Ok(detail)

    class _Mgr:
        store = None

    monkeypatch.setattr(prefix_resolver, "resolve_or_raise", _resolve)
    monkeypatch.setattr(sessions, "get_projection_mgr", _Mgr)
    monkeypatch.setattr(sessions, "get_session", _get_session)
    return await sessions.get_session_endpoint(detail.id)


@pytest.mark.asyncio
async def test_session_on_opus_5_5_reports_its_own_rates(monkeypatch: pytest.MonkeyPatch) -> None:
    response = await _session_response(
        monkeypatch,
        SessionDetail(
            id="s-1",
            status="completed",
            agent_model=OPUS,
            cost_by_model={OPUS: Decimal("0.3056678")},
        ),
    )
    assert response.cache_read_rate_display == "0.05x rate"
    assert response.cache_write_rate_display == "1.25x rate"


@pytest.mark.asyncio
async def test_session_without_a_breakdown_uses_its_reported_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = await _session_response(
        monkeypatch, SessionDetail(id="s-2", status="running", agent_model=SOL)
    )
    assert response.cache_read_rate_display == "0.1x rate"
    assert response.cache_write_rate_display == "1.25x rate"


@pytest.mark.asyncio
async def test_session_with_unknown_model_has_no_labels(monkeypatch: pytest.MonkeyPatch) -> None:
    response = await _session_response(
        monkeypatch,
        SessionDetail(
            id="s-3",
            status="completed",
            cost_by_model={"not-a-real-model": Decimal("0.1")},
        ),
    )
    assert response.cache_read_rate_display is None
    assert response.cache_write_rate_display is None
