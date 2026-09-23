"""SessionObservationPort - where a session's telemetry is written.

The agent_sessions context owns two records of the same moment. The aggregate
owns what the operation MEANS to the session (its tokens, its count, whether a
completed session may record another). The observation lane owns what the
operation LOOKED LIKE, and it is the only lane ``GET /sessions/{id}`` reads for
``operations`` (#1034, commit 84b28fea).

Before this port, the write path reached only the first of those, so every
operation recorded through ``RecordOperationHandler`` was real, durable, and
invisible at the endpoint named after it.

The protocol is deliberately the same shape the observability writer already
exposes, so the existing adapter satisfies it structurally with no wrapper: a
port that only forwards arguments hides nothing and earns nothing.
"""

from __future__ import annotations

from typing import Any, Protocol

from syn_domain.contexts.agent_sessions.domain.events.agent_observation import (
    ObservationType,  # noqa: TC001
)


class SessionObservationPort(Protocol):
    """Port: records one agent observation on the session's telemetry lane."""

    async def record_observation(
        self,
        session_id: str,
        observation_type: ObservationType | str,
        data: dict[str, Any],
        execution_id: str | None = None,
        phase_id: str | None = None,
        workspace_id: str | None = None,
    ) -> None:
        """Append one observation for ``session_id``.

        ``data`` is the type-specific payload documented on
        ``AgentObservationEvent``; the reader keys off ``observation_type`` to
        interpret it. Implementations MAY raise - the caller is responsible for
        deciding whether a telemetry failure is worth failing a command over.
        """
        ...
