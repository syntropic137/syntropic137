"""Port for recovering a delegated child's harness-native session id.

WHY this is a port and not an implementation (issue #895): knowing that
``codex exec --json`` announces itself with ``thread.started.thread_id`` is
knowledge about a CLI, not about our domain. It changes when OpenAI ships a new
codex version, and per the boundary rule in AGENTS.md that puts it in
agentic-primitives, beside the existing ``harnesses/{claude,codex}`` adapters
which already normalize to ``HarnessTranscript``.

Depending on this shape rather than on a format has two consequences worth
stating, because both were the reason for choosing it:

1. **The domain is testable without the submodule.** A delegated child is bound
   to its parent by domain code that never parses a stream, so these tests run
   against a double.
2. **This work does not serialise behind the image.** A change in
   agentic-primitives reaches a workspace only after merge, image build, the
   protected release channel and a ``PINNED_DIGESTS`` bump. Defining the
   contract here lets both sides proceed in parallel.

The binding this feeds is two-step by necessity: the platform mints a
``delegation_attempt_id`` BEFORE launch, and the child's native id does not
exist until the child starts. Whichever adapter minted the attempt id reads the
child's own stream, so concurrent children of one provider never need
correlating by time or arrival order.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class DelegateIdentityPort(Protocol):
    """Recovers a harness's own session id from a line of its output stream.

    ``runtime_checkable`` so production wiring can assert it was handed a real
    adapter rather than discovering a missing method at delegation time, when
    the child is already running and the failure is expensive.
    """

    def native_session_id_from_stream(self, line: str) -> str | None:
        """Return the harness-native session id this line announces.

        Implementations MUST return ``None`` for any line that does not
        actually carry identity, rather than reading an id-shaped field from
        wherever one appears. agentic-primitives already learned this: reading
        ``session_id`` off any line let an unrelated session's id through
        (#792), which binds a child to the wrong parent while looking like it
        worked.

        An empty id is not an id, and must also return ``None``: it would bind
        the child to nothing while reporting success.

        Args:
            line: One line of the delegate's output stream.

        Returns:
            The native session id, or None if this line does not announce one.
        """
        ...
