"""Port for recovering the transcript codex persisted for one of its sessions.

WHY THIS IS A PORT (issue #1284). Codex names the model it ran on disk and
nowhere on its stdout stream, so the rollout is the only observation of a codex
phase's identity that exists. Reaching it means knowing where codex keeps its
sessions (``$CODEX_HOME/sessions/...``, matched by session id) and how to read
a file out of a container that may not be on this machine. Both are knowledge
about a CLI and a transport, not about the domain, so per the boundary rule in
AGENTS.md they belong on the far side of an interface - the workspace adapter
already owns the transport and agentic-workspace already owns the layout.

WHAT DELIBERATELY STAYS ON THIS SIDE: what a rollout MEANS. The records come
back as they were written and ``model_from_rollout`` reads them, so the field
that names a model has exactly one reader in this system and the domain can be
tested against a real captured rollout without a container anywhere near it.
Putting the parse behind the port instead would buy a narrower signature and
pay for it with a second reader and a test that can only assert a value it
made up itself.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from syn_domain.contexts.agent_sessions import RolloutDocument


class CodexRolloutPort(Protocol):
    """Hands back the rollout codex wrote for a session, if it can be read."""

    async def codex_rollout(self, native_session_id: str) -> RolloutDocument | None:
        """The records codex persisted under ``native_session_id``.

        ``native_session_id`` is the id CODEX chose and announced on
        ``thread.started`` - the namespace its own rollout files are filed
        under - never the platform's session id, which codex has never seen.
        It is how an implementation tells one session's rollout from another's;
        it is not a promise that a rollout it cannot match is unreachable.

        Returns ``None``, and only ``None``, when the rollout COULD NOT BE
        READ: nothing was persisted, the workspace was gone, the read failed. An empty document means the opposite - the rollout was
        read and says nothing. The caller reports a model of ``None`` either
        way, but only one of the two is an operational fault, and an
        implementation that collapses them makes an unreachable workspace look
        like a silent codex.

        Implementations MUST NOT raise. A transcript this phase's result does
        not depend on must never be the thing that fails it.
        """
        ...
