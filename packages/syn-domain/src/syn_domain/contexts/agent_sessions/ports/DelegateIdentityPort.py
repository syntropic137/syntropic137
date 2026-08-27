"""Port for recovering a delegated child's harness-native session id.

WHY this is a port and not an implementation (issue #895): how a harness
announces its own session id is knowledge about a CLI, not about our domain. It
changes when a vendor ships a new version, and per the boundary rule in
AGENTS.md that puts it in agentic-primitives, beside the existing
``harnesses/{claude,codex}`` adapters which already normalize to
``HarnessTranscript``. This module deliberately names no CLI, no event type and
no field: if a format appears here, the abstraction has failed.

Depending on this shape rather than on a format has two consequences, and both
were the reason for choosing it:

1. **The domain is testable without the submodule.** A delegated child is bound
   to its parent by domain code that never parses a stream.
2. **This work does not serialise behind the image.** A change in
   agentic-primitives reaches a workspace only after merge, image build, the
   protected release channel and a ``PINNED_DIGESTS`` bump.

The binding this feeds is two-step by necessity: the platform mints a
``delegation_attempt_id`` BEFORE launch, and the child's native id does not
exist until the child starts. Whichever adapter minted the attempt id reads
that child's own stream, so concurrent children of one provider never need
correlating by time or arrival order.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class DelegateIdentityPort(Protocol):
    """Recovers a harness's own session id from a line of its output stream.

    ``runtime_checkable`` buys ONE narrow thing: a shallow check that the
    method NAME is present, so wiring fails at startup rather than at
    delegation time when a child is already running. It proves nothing about
    the signature, the return type, or the behaviour. ``isinstance`` passes for
    an object whose ``native_session_id_from_stream`` is the integer 42. Do not
    read it as evidence that a real adapter was supplied.
    """

    def native_session_id_from_stream(self, line: str) -> str | None:
        """Return the harness-native session id this line announces.

        Implementations MUST return ``None``, never raise and never guess, for:

        - a line that does not announce identity, even when it carries an
          id-shaped field. agentic-primitives already learned this the hard
          way: reading an id off ANY line let an unrelated session's id
          through (#792), which binds a child to the wrong parent while
          looking like it worked;
        - an empty id, which would bind the child to nothing while reporting
          success;
        - a malformed or unparseable line. A delegate's stream is not
          guaranteed well-formed, and a parse error raised here would abort a
          binding over a line that was never going to carry identity anyway.

        Args:
            line: One line of the delegate's output stream.

        Returns:
            The native session id, or None if this line does not announce one.
        """
        ...
