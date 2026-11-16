"""Port for recovering what codex's persisted transcript says about a session.

WHY THIS IS A PORT (issue #1284). Codex names the model it ran on disk and
nowhere on its stdout stream, so the rollout is the only observation of a codex
phase's identity that exists. Reaching it means knowing where codex keeps its
sessions (``$CODEX_HOME/sessions/...``, matched by session id) and how to read
a file out of a container that may not be on this machine. Both are knowledge
about a CLI and a transport, not about the domain, so per the boundary rule in
AGENTS.md they belong on the far side of an interface - the workspace adapter
already owns the transport and agentic-workspace already owns the layout.

HOW a rollout spells its model (``turn_context.payload.model``) is the same
kind of knowledge: it changes when codex ships, not when we decide what a model
is. So the reader of that field lives in the adapter too (#1424), and this port
hands back what the rollout SAYS rather than the records it says it in. What
stays on this side is the meaning: which model is reported, and the difference
between a rollout that could not be read and one that names nothing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class CodexRolloutReading:
    """A rollout that WAS read, and the one model it names.

    ``model`` is None when the rollout names no model AND when it names
    several: a session that spanned models cannot be attributed to one of them,
    and naming whichever came first would read as evidence. Never ``""``: a
    blank model names nothing.
    """

    model: str | None


class CodexRolloutPort(Protocol):
    """Reads the rollout codex wrote for a session, if it can be read."""

    async def codex_rollout_model(self, native_session_id: str) -> CodexRolloutReading | None:
        """What the rollout codex persisted under ``native_session_id`` says.

        ``native_session_id`` is the id CODEX chose and announced on
        ``thread.started`` - the namespace its own rollout files are filed
        under - never the platform's session id, which codex has never seen.
        It is how an implementation tells one session's rollout from another's;
        it is not a promise that a rollout it cannot match is unreachable.

        Returns ``None``, and only ``None``, when the rollout COULD NOT BE
        READ: nothing was persisted, the workspace was gone, the read failed.
        A reading whose ``model`` is None means the opposite - the rollout was
        read and names no single model. The caller reports a model of ``None``
        either way, but only one of the two is an operational fault, and an
        implementation that collapses them makes an unreachable workspace look
        like a silent codex.

        Implementations MUST NOT raise. A transcript this phase's result does
        not depend on must never be the thing that fails it.
        """
        ...
