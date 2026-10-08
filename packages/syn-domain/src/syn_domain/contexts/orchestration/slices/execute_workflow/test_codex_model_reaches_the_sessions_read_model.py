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

COMPOSITE FIXTURE. The stdout recording and the rollout are two independent
real captures: the recording announces thread `019f8f89-...`, the rollout was
written by a different codex session. No matching pair has been captured. So
this proves the model is carried from the port to the read model, not that a
real workspace files this rollout under this id. The port double is bound to
the id the recording announces and serves nothing for any other id, so the
processor must still ask for the right one; the production lookup by that id
is pinned separately (`test_the_rollout_is_asked_for_by_the_id_codex_announced`
here, and agentic-workspace's `codex_rollout` for the file itself).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

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
from syn_shared.events import SESSION_SUMMARY, TOKEN_USAGE
from syn_shared.observed_model import (
    OBSERVED_MODEL_KEY,
    REQUESTED_MODEL_KEY,
    format_observed_model,
)

if TYPE_CHECKING:
    from syn_domain.contexts.agent_sessions.domain.events.agent_observation import (
        ObservationType,
    )
    from syn_domain.contexts.orchestration.ports.CodexRolloutPort import RolloutDocument

pytestmark = pytest.mark.unit

SESSION_ID = "sess-codex-1"

_RECORDING = _FIXTURES_DIR / "codex_exec_recording.jsonl"


def _announced_thread_id() -> str:
    """The id the real recording's `thread.started` announces."""
    for line in _RECORDING.read_text().splitlines():
        if line.startswith("{"):
            record = json.loads(line)
            if record.get("type") == "thread.started":
                return str(record["thread_id"])
    raise AssertionError(f"{_RECORDING} announces no thread")


#: The native id the rollout double is bound to. The platform's SESSION_ID is
#: deliberately different, so a lookup by the wrong one is served nothing.
NATIVE_ID = _announced_thread_id()


class _RolloutForTheAnnouncedThread:
    """A `CodexRolloutPort` holding one rollout, filed under `NATIVE_ID` only."""

    def __init__(self, document: RolloutDocument | None) -> None:
        self._document = document
        self.asked_for: list[str] = []

    async def codex_rollout(self, native_session_id: str) -> RolloutDocument | None:
        self.asked_for.append(native_session_id)
        return self._document if native_session_id == NATIVE_ID else None


@dataclass(frozen=True)
class _WrittenRow:
    """One observation as the collector wrote it, before any projection read it."""

    kind: str
    model: object
    requested_model: object


class _ObservationsToProjection:
    """An observability writer that delivers each row to the session_cost projection.

    The shape is the one the projection is subscribed to: `event_type` is the
    observation type, and `data` is the row the collector wrote, untouched.
    Usage and tool rows go to `on_agent_observation` and the summary goes to
    `on_session_summary`, the same routing as `projection_adapters`.
    """

    def __init__(self, projection: SessionCostProjection) -> None:
        self._projection = projection
        #: Every row the collector wrote, with the two model fields it carried.
        self.rows: list[_WrittenRow] = []

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
        self.rows.append(
            _WrittenRow(kind, data.get(OBSERVED_MODEL_KEY), data.get(REQUESTED_MODEL_KEY))
        )
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
    rollout: _RolloutForTheAnnouncedThread,
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
    await processor.process_stream(_lines(_RECORDING), MockWorkspace())
    assert rollout.asked_for == [NATIVE_ID]
    return projection, writer


class TestTheSessionsReadModelNamesTheModelCodexRan:
    async def test_the_rollout_model_is_the_sessions_agent_model(self) -> None:
        """`gpt-5.6-sol` is written only in the rollout's `turn_context`.

        The recording never names it, and the phase requested a different
        model, so the read model can only hold this value if it was carried
        all the way through.
        """
        projection, writer = await _run_the_recording(
            _RolloutForTheAnnouncedThread(_real_rollout())
        )

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
        usage_rows = [row for row in writer.rows if row.kind == TOKEN_USAGE]
        assert usage_rows
        for row in usage_rows:
            assert row.model == CODEX_ANNOUNCED

    async def test_with_no_rollout_the_read_model_says_unknown_not_the_request(self) -> None:
        """The counterweight to the case above. When the rollout cannot be
        read, the session is honestly unknown, and the requested alias is
        never promoted to the model that ran."""
        projection, writer = await _run_the_recording(_RolloutForTheAnnouncedThread(None))

        # At the source, before any projection could demote an alias: every
        # row that carries a model says none was observed, and the request
        # travels in its own field.
        model_rows = [row for row in writer.rows if row.kind in (TOKEN_USAGE, SESSION_SUMMARY)]
        assert {row.kind for row in writer.rows} >= {TOKEN_USAGE, SESSION_SUMMARY}
        for row in model_rows:
            assert row.model is None
            assert row.requested_model == REQUESTED_BY_A_CODEX_PHASE

        cost = await projection.get_session_cost(SESSION_ID)

        assert cost is not None
        assert cost.agent_model is None
        assert format_observed_model(cost.agent_model, cost.requested_model) == (
            f"unknown (requested: {REQUESTED_BY_A_CODEX_PHASE})"
        )
