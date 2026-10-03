"""A codex phase on the `gpt-sol` default: priced, and honestly identified (R2).

`gpt-sol` is a platform alias. It is what the phase STORES and REQUESTS; the
command builder sends codex the concrete slug `gpt-6-sol` (pinned in
``apps/syn-api/tests/test_codex_model_alias_argv.py``). Two separate claims
follow, and each gets its own evidence:

- COST comes from the requested model, because codex does not report its
  model on the wire. The alias must therefore resolve to gpt-6-sol's rate.
- IDENTITY (``announced_model``) comes only from the rollout. With a readable
  rollout it is what codex wrote there; without one it stays ``None`` - never
  the requested alias, and never a slug synthesized from it.
"""

from __future__ import annotations

import copy
import json
from decimal import Decimal

import pytest

from syn_domain.contexts.orchestration.slices.execute_workflow.test_announced_model_is_not_the_requested_one import (
    CODEX_THREAD_ID,
    _codex_thread_started,
    _codex_turn_completed,
    _real_rollout,
    _RolloutOnDisk,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.test_codex_stream_processor import (
    _FIXTURES_DIR,
    _lines,
    _make_processor,
    _NoopWorkspace,
    _RecordingCollector,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.test_event_stream_processor import (
    _lines_to_stream,
)
from syn_shared.agents import DEFAULT_CODEX_MODEL, CodexModelAlias, ModelId
from syn_shared.pricing import require_model_pricing

pytestmark = pytest.mark.unit


def _rollout_naming(model: str) -> _RolloutOnDisk:
    """The real captured rollout with its turn_context model set to ``model``.

    Only the model VALUE changes. The probe of codex 0.156.1 in the bumped
    omni-agent image (2026-09-24) recorded ``"model": "gpt-6-sol"`` in exactly
    this field, so the shape is real and so is the value.
    """
    document = copy.deepcopy(_real_rollout())
    for record in document:
        if record.get("type") == "turn_context":
            record["payload"]["model"] = model
    return _RolloutOnDisk(document)


class TestTheDefaultIsPriced:
    async def test_a_gpt_sol_phase_is_priced_at_gpt_6_sol_rates(self) -> None:
        collector = _RecordingCollector()
        processor, _ = _make_processor(collector, agent_model=DEFAULT_CODEX_MODEL)

        result = await processor.process_stream(
            _lines(_FIXTURES_DIR / "codex_exec_recording.jsonl"), _NoopWorkspace()
        )

        assert result.reported_usage is not None
        expected = require_model_pricing(ModelId.GPT_6_SOL).calculate_cost(
            result.reported_usage.input_tokens,
            result.reported_usage.output_tokens,
            cache_read=result.reported_usage.cache_read,
        )
        summary = next(c[1] for c in collector.calls if c[0] == "summary")
        assert summary["total_cost_usd"] is not None
        assert Decimal(str(summary["total_cost_usd"])) == pytest.approx(expected)

    async def test_the_default_is_the_alias_not_an_unpriced_string(self) -> None:
        assert DEFAULT_CODEX_MODEL == CodexModelAlias.GPT_SOL
        assert require_model_pricing(DEFAULT_CODEX_MODEL).model_id is ModelId.GPT_6_SOL


class TestTheIdentityComesOnlyFromTheRollout:
    async def test_a_readable_rollout_names_the_model_that_ran(self) -> None:
        rollout = _rollout_naming(ModelId.GPT_6_SOL)
        processor, _ = _make_processor(
            _RecordingCollector(), agent_model=DEFAULT_CODEX_MODEL, rollout=rollout
        )

        result = await processor.process_stream(
            _lines_to_stream(_codex_thread_started(), _codex_turn_completed()), _NoopWorkspace()
        )

        assert rollout.asked_for == [CODEX_THREAD_ID]
        assert result.announced_model == ModelId.GPT_6_SOL

    async def test_an_unreadable_rollout_leaves_the_model_unknown(self) -> None:
        """No fallback to the request: not `gpt-sol`, and not a `gpt-6-sol`
        synthesized from it. What ran is unknown, so it is recorded as such."""
        rollout = _RolloutOnDisk(None)
        processor, _ = _make_processor(
            _RecordingCollector(), agent_model=DEFAULT_CODEX_MODEL, rollout=rollout
        )

        result = await processor.process_stream(
            _lines_to_stream(_codex_thread_started(), _codex_turn_completed()), _NoopWorkspace()
        )

        assert rollout.asked_for == [CODEX_THREAD_ID]
        assert result.announced_model is None

    async def test_cost_is_still_priced_when_the_identity_is_unknown(self) -> None:
        """The two claims are independent: an unreadable rollout loses the
        observed model, not the price of the model that was requested."""
        collector = _RecordingCollector()
        processor, _ = _make_processor(
            collector, agent_model=DEFAULT_CODEX_MODEL, rollout=_RolloutOnDisk(None)
        )

        await processor.process_stream(
            _lines_to_stream(
                _codex_thread_started(),
                json.dumps(
                    {
                        "type": "turn.completed",
                        "usage": {"input_tokens": 1_000_000, "output_tokens": 0},
                    }
                ),
            ),
            _NoopWorkspace(),
        )

        summary = next(c[1] for c in collector.calls if c[0] == "summary")
        assert summary["total_cost_usd"] == pytest.approx(2.00)
