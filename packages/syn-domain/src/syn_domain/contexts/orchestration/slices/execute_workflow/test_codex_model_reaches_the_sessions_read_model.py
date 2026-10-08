"""A codex session's model, from the recorded stream to the sessions read model.

Owner feedback 58868cd8: codex sessions on the Sessions page said "unknown".
The model comes from the rollout file because codex never names it on stdout
(#1284). The existing tests pin each hop in isolation. The processor returns
`announced_model`, and the projection reads a row's `model`. A value
returned correctly at the first hop and dropped before the second would pass
both. So this test feeds the real recording, with the real rollout, through the
real `CodexStreamProcessor` and the real `ObservabilityCollector`. Every
observation it writes is delivered to `SessionCostProjection`, which is the
read model `/sessions` enriches from (`_enrichment_from_cost`), and the
assertion is on what that read model says.

The only doubles are the two edges this package cannot own. One is the
rollout port, which serves the captured document. The other is the
observability writer, which hands each row to the projection in the shape the
subscription delivers it.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from syn_domain.contexts.agent_sessions.domain.events.agent_observation import ObservationType
from syn_domain.contexts.agent_sessions.slices.session_cost.projection import (
    SessionCostProjection,
)
from syn_domain.contexts.agent_sessions.slices.session_cost.test_projection import (
    MockProjectionStore,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.CodexStreamProcessor import (
    CodexStreamProcessor,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.ObservabilityCollector import (
    ObservabilityCollector,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.test_announced_model_is_not_the_requested_one import (
    CODEX_ANNOUNCED,
    REQUESTED_BY_A_CODEX_PHASE,
    _real_rollout,
    _RolloutOnDisk,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.test_codex_stream_processor import (
    _FIXTURES_DIR,
    _lines,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.test_event_stream_processor import (
    MockWorkspace,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.TokenAccumulator import (
    TokenAccumulator,
)
from syn_shared.events import SESSION_SUMMARY
from syn_shared.observed_model import OBSERVED_MODEL_KEY, format_observed_model

pytestmark = pytest.mark.unit

SESSION_ID = "sess-codex-1"


class _ObservationsToProjection:
    """An observability writer that delivers each row to the session_cost projection.

    The shape is the one the projection is subscribed to: `event_type` is the
    observation type, and `data` is the row the collector wrote, untouched.
    Usage and tool rows go to `on_agent_observation` and the summary goes to
    `on_session_summary`, the same routing as `projection_adapters`.
    """

    def __init__(self, projection: SessionCostProjection) -> None:
        self._projection = projection
        #: The `model` each row was written with, by observation type.
        self.models: list[tuple[str, object]] = []

    async def record_observation(
        self,
        session_id: str,
        observation_type: ObservationType | str,
        data: object,
        execution_id: str | None = None,
        phase_id: str | None = None,
        workspace_id: str | None = None,
    ) -> None:
        assert isinstance(data, dict)
        kind = str(getattr(observation_type, "value", observation_type))
        self.models.append((kind, data.get(OBSERVED_MODEL_KEY)))
        deliver = (
            self._projection.on_session_summary
            if kind == SESSION_SUMMARY
            else self._projection.on_agent_observation
        )
        await deliver(
            {
                "session_id": session_id,
                "execution_id": execution_id,
                "phase_id": phase_id,
                "workspace_id": workspace_id,
                "event_type": kind,
                "timestamp": datetime.now(UTC).isoformat(),
                "data": data,
            }
        )


async def _run_the_recording(
    rollout: _RolloutOnDisk,
) -> tuple[SessionCostProjection, _ObservationsToProjection]:
    projection = SessionCostProjection(MockProjectionStore())
    writer = _ObservationsToProjection(projection)
    collector = ObservabilityCollector(
        writer=writer,
        session_id=SESSION_ID,
        execution_id="exec-1",
        phase_id="p1",
        workspace_id=None,
        requested_model=REQUESTED_BY_A_CODEX_PHASE,
    )
    processor = CodexStreamProcessor(
        tokens=TokenAccumulator(),
        collector=collector,
        controller=None,
        execution_id="exec-1",
        phase_id="p1",
        session_id=SESSION_ID,
        agent_model=REQUESTED_BY_A_CODEX_PHASE,
        rollout=rollout,
    )
    await processor.process_stream(
        _lines(_FIXTURES_DIR / "codex_exec_recording.jsonl"), MockWorkspace()
    )
    return projection, writer


class TestTheSessionsReadModelNamesTheModelCodexRan:
    async def test_the_rollout_model_is_the_sessions_agent_model(self) -> None:
        """`gpt-5.6-sol` is written only in the rollout's `turn_context`.

        The recording never names it, and the phase requested a different
        model, so the read model can only hold this value if it was carried
        all the way through.
        """
        projection, writer = await _run_the_recording(_RolloutOnDisk(_real_rollout()))

        cost = await projection.get_session_cost(SESSION_ID)

        assert cost is not None
        assert cost.agent_model == CODEX_ANNOUNCED
        assert cost.requested_model == REQUESTED_BY_A_CODEX_PHASE
        assert format_observed_model(cost.agent_model, cost.requested_model) == CODEX_ANNOUNCED
        # The run recorded usage at all, so the model has rows to be attributed to.
        assert cost.total_tokens > 0
        assert cost.tokens_by_model == {CODEX_ANNOUNCED: cost.total_tokens}
        # Each hop carries the model, not just the summary. A replay that stops
        # before the summary, or a live view between turns, reads the
        # per-turn rows.
        usage_models = {
            model for kind, model in writer.models if kind == ObservationType.TOKEN_USAGE.value
        }
        assert usage_models == {CODEX_ANNOUNCED}

    async def test_with_no_rollout_the_read_model_says_unknown_not_the_request(self) -> None:
        """The counterweight to the case above. When the rollout cannot be
        read, the session is honestly unknown, and the requested alias is
        never promoted to the model that ran."""
        projection, _ = await _run_the_recording(_RolloutOnDisk(None))

        cost = await projection.get_session_cost(SESSION_ID)

        assert cost is not None
        assert cost.agent_model is None
        assert format_observed_model(cost.agent_model, cost.requested_model) == (
            f"unknown (requested: {REQUESTED_BY_A_CODEX_PHASE})"
        )
