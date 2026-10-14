"""Agentic event stream adapter - real-time agent output for observability.

The agent runs as an operation on agentic-workspace's provider contract:
``start`` launches it detached, ``observe`` pages its output, ``status`` says
how it ended. This module never spawns a process itself; the provider owns the
transport, and how it execs into a container is its decision, not ours.

See ADR-021: Isolated Workspace Architecture, and
docs/plans/20261013_provider-operation-contract.md section 5.3.
"""

from __future__ import annotations

import base64
import codecs
import logging
import math
import posixpath
import signal
import uuid
from typing import TYPE_CHECKING, Protocol

from agentic_isolation.contract import (
    MISSING,
    LaunchMarker,
    ObservationGap,
    OperationSpec,
)

from syn_adapters.diagnostics import capture_signal_death
from syn_adapters.workspace_backends.agentic.credential_scrubber import CredentialScrubber
from syn_domain.contexts.orchestration import announce_as, mint_wrapper_name
from syn_shared.diagnostics import SignalDeath, name_exit_status

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Iterable

    from agentic_isolation.contract import OperationRef, OperationStatus
    from agentic_isolation.providers.base import SupportsOperations, Workspace

    from syn_adapters.workspace_backends.agentic.credentials import WorkspaceCredentials
    from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
        IsolationHandle,
    )

logger = logging.getLogger(__name__)

#: GNU ``timeout``'s conventional status for "killed because the time limit
#: elapsed". NOT 128+SIGTERM, which would be 143. The local isolation provider
#: already uses 124 for the same meaning, and nothing in the execution path
#: interprets specific exit codes -- cancellation is driven by
#: ``interrupt_requested``, not by a status number -- so this cannot be
#: mistaken for a cancel.
_TIMEOUT_EXIT_CODE = 124

#: The contract requires a positive timeout. A caller that asked for none gets
#: a week: longer than any phase deadline, so the phase's own budget is still
#: what ends a run.
_UNBOUNDED_TIMEOUT_SECONDS = 7 * 24 * 3600

#: Largest page asked for per ``observe``; the provider may return less.
_PAGE_BYTES = 1 << 20

#: How long one ``observe`` may wait for output before returning an empty page.
_OBSERVE_WAIT_SECONDS = 1.0

#: Given to the operation to exit on its own when the reader stops early.
_CANCEL_GRACE_SECONDS = 5.0

_CONTAINER_WORKSPACE = "/workspace"


def _resolve_stream_exit_code(exit_code: int | None, *, timed_out: bool) -> int | None:
    """Return the status a truncated stream should report.

    Pure and module-level so the decision is testable without a container.

    A timed-out operation whose status reads as success becomes
    ``_TIMEOUT_EXIT_CODE``: success cannot be believed of a run the provider
    had to stop.

    An already-failing status is left ALONE: it is more specific than "timed
    out" and the operator needs the real one. A stream that was not truncated is
    never rewritten, which is what keeps cancellation (driven by
    ``interrupt_requested``, not by a status) out of this path.
    """
    if timed_out and not exit_code:
        return _TIMEOUT_EXIT_CODE
    return exit_code


def _exit_code_of(status: OperationStatus) -> int | None:
    """The shell-convention status: the exit code, or 128+n for a named signal."""
    exit_code = status.exit_code if status.exit_code is not MISSING else None
    if exit_code is not None:
        return exit_code
    name = status.signal if status.signal is not MISSING else None
    if name:
        try:
            return 128 + signal.Signals[name if name.startswith("SIG") else f"SIG{name}"]
        except KeyError:
            logger.warning("Operation ended on unknown signal %r", name)
    return None


def _relative_working_directory(working_directory: str | None) -> str:
    """The contract's working directory: relative to the workspace root."""
    if not working_directory:
        return "."
    return posixpath.relpath(posixpath.normpath(working_directory), _CONTAINER_WORKSPACE)


def _timeout_seconds(timeout_seconds: float | None) -> int:
    """Positive whole seconds, rounded UP so a fractional budget is never cut short."""
    if not timeout_seconds or timeout_seconds <= 0:
        return _UNBOUNDED_TIMEOUT_SECONDS
    return max(1, math.ceil(timeout_seconds))


class LineDecoder:
    """Turns observation pages into lines, whatever a page boundary splits.

    A page may end mid-code-point or mid-line. The incremental decoder holds a
    split code point until its remaining bytes arrive; the buffer holds a split
    line until its newline does. ``finish`` flushes the final unterminated line.
    Empty lines are dropped and ``\r\n`` endings stripped, as before.
    """

    def __init__(self) -> None:
        self._decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        self._partial = ""

    def feed(self, data: bytes) -> list[str]:
        text = self._partial + self._decoder.decode(data)
        *complete, self._partial = text.split("\n")
        return [line for line in (c.rstrip("\r") for c in complete) if line]

    def gap(self) -> int:
        """Drop the partial line a gap has severed; return how many chars went."""
        dropped = len(self._partial) + len(self._decoder.decode(b"", final=True))
        self._decoder.reset()
        self._partial = ""
        return dropped

    def finish(self) -> list[str]:
        text = self._partial + self._decoder.decode(b"", final=True)
        self._partial = ""
        line = text.rstrip("\r")
        return [line] if line else []


class OperationHost(Protocol):
    """What the stream needs from the isolation adapter: the contract, its workspaces, its credentials."""

    @property
    def operations(self) -> SupportsOperations: ...

    def workspace(self, isolation_id: str) -> Workspace | None: ...

    @property
    def credentials(self) -> WorkspaceCredentials: ...


class AgenticEventStreamAdapter:
    """Implements EventStreamPort on agentic-workspace's provider operation contract."""

    def __init__(self, host: OperationHost) -> None:
        self._host = host
        self._last_exit_code: int | None = None
        self._last_signal_death: SignalDeath | None = None
        self._last_lost_bytes: int | None = None

    @property
    def last_signal_death(self) -> SignalDeath | None:
        """Why the most recent stream() call's process was KILLED, if it was.

        Paired with :attr:`last_exit_code` and read the same way: it belongs to
        the last stream and is replaced by the next. None means the process was
        not killed by a signal, or that no stream has run.
        """
        return self._last_signal_death

    @property
    def last_exit_code(self) -> int | None:
        """Exit code from the most recent stream() call.

        Returns None if no stream has completed yet.
        """
        return self._last_exit_code

    @property
    def last_observation_lost_bytes(self) -> int | None:
        """Output the provider evicted before the last stream read it.

        0 when nothing was lost, -1 when the provider reported a gap of unknown
        size, None when no stream has run. Never silently zero: a gap is also
        logged at ERROR the moment it is seen.
        """
        return self._last_lost_bytes

    async def stream(
        self,
        handle: IsolationHandle,
        command: list[str],
        *,
        timeout_seconds: int | None = None,
        working_directory: str | None = None,
        environment: dict[str, str] | None = None,
        wrapper_name: str | None = None,
        withheld: Callable[[], Iterable[str]] | None = None,
    ) -> AsyncIterator[str]:
        """Stream the agent's output lines as the provider observes them.

        Args:
            handle: Handle from isolation adapter
            command: Command to execute
            timeout_seconds: Max execution time, rounded up to whole seconds
            working_directory: Working directory override
            environment: Additional environment variables. Any the contract
                names a credential (the platform grant's token) are delivered
                as launch-scoped credential bindings, never as plain values.
            wrapper_name: The ``$0`` the container-side launcher announces
                itself under, from ``AgentLaunchEvidence.wrapper_name``. NOT
                passed through ``environment``: the agent inherits that, and a
                name the agent can read is a name it can forge (#1065). It
                reaches the provider as the spec's ``launch_marker``, which the
                provider passes on stdin and ``exec`` then replaces.
            withheld: Further credential values the workload holds (its GitHub
                tokens), read again before every page because a renewal adds
                new ones while the stream runs.

        Yields:
            Individual output lines as they are produced, with every credential
            value replaced (#1927): the launch's own credentials, the
            session-store token and ``withheld``. See ``credential_scrubber``.

        ARCHITECTURE NOTE - one stream, stdout and stderr together (ADR-043):
        the operation's observation stream carries both channels in arrival
        order, so nothing the agent writes is discarded. Git hook JSONL
        arrives EMBEDDED inside stream-json tool_result content, which
        WorkflowExecutionEngine scans; it is never a separate channel.
        """
        workspace = self._host.workspace(handle.isolation_id)
        if workspace is None:
            raise RuntimeError(f"Workspace not found: {handle.isolation_id}")
        provider = self._host.operations
        credentials = self._host.credentials

        plain, bindings, parked = credentials.bind_launch(environment or {})
        bound = credentials.withheld(parked)
        try:
            wrapper = wrapper_name if wrapper_name is not None else mint_wrapper_name()
            spec = OperationSpec(
                schema=MISSING,
                execution_id=handle.isolation_id,
                operation_key=uuid.uuid4().hex,
                argv=tuple(command),
                working_directory=_relative_working_directory(working_directory),
                environment=plain,
                credential_bindings=bindings,
                launch_marker=LaunchMarker(argv0=wrapper, line=announce_as(wrapper)),
                timeout_seconds=_timeout_seconds(timeout_seconds),
                metadata={},
            )
            self._last_exit_code = None
            self._last_signal_death = None
            self._last_lost_bytes = 0
            ref = await provider.start(workspace, spec)
        finally:
            # Resolved during start, or never needed when the spec or the start
            # failed: no launch value outlives this block either way.
            credentials.release(parked)
        logger.debug(
            "Started stream operation %s (cmd=%s)",
            ref.operation_id,
            CredentialScrubber(bound).scrub(str(command)),
        )

        def secrets() -> tuple[str, ...]:
            return (*bound, *(withheld() if withheld is not None else ()))

        try:
            async for line in self._observe(provider, ref, secrets):
                yield line
            status = await provider.status(ref)
        except BaseException:
            # The reader stopped early, was cancelled, or observation failed:
            # the operation must not outlive the stream nobody is reading. The
            # primary failure stays primary - a cancel or settle that also
            # fails is logged with its cause, never raised in its place.
            try:
                await self._settle(
                    await provider.cancel(ref, grace_seconds=_CANCEL_GRACE_SECONDS), spec
                )
            except Exception:
                logger.exception(
                    "Cancelling stream operation %s after it stopped also failed",
                    ref.operation_id,
                )
            raise
        await self._settle(status, spec)

    async def _observe(
        self,
        provider: SupportsOperations,
        ref: OperationRef,
        secrets: Callable[[], Iterable[str]],
    ) -> AsyncIterator[str]:
        """Yield the operation's output as scrubbed lines.

        Scrubbing whole lines is what makes a value split across two pages
        safe: the decoder carries the unterminated part of a line into the
        next page, so no line is scrubbed until all of it has arrived.
        """
        decoder = LineDecoder()
        scrubber = CredentialScrubber()
        cursor: str | None = None
        while True:
            page = await provider.observe(
                ref, cursor=cursor, max_bytes=_PAGE_BYTES, wait_seconds=_OBSERVE_WAIT_SECONDS
            )
            current = tuple(secrets())
            if not scrubber.covers(current):
                scrubber = CredentialScrubber(current)
            if isinstance(page.gap, ObservationGap):
                self._record_gap(page.gap, decoder.gap(), ref)
            for line in decoder.feed(base64.b64decode(page.data_b64)):
                yield scrubber.scrub(line)
            cursor = page.next_cursor
            if page.complete:
                for line in decoder.finish():
                    yield scrubber.scrub(line)
                return

    def _record_gap(self, gap: ObservationGap, severed_chars: int, ref: OperationRef) -> None:
        if gap.lost_bytes is None or self._last_lost_bytes == -1:
            self._last_lost_bytes = -1
        else:
            self._last_lost_bytes = (self._last_lost_bytes or 0) + gap.lost_bytes
        logger.error(
            "Agent output LOST before it was read (operation=%s): %s bytes evicted by the "
            "provider, %d chars of a severed line dropped. Events in that span are missing.",
            ref.operation_id,
            "an unknown number of" if gap.lost_bytes is None else gap.lost_bytes,
            severed_chars,
        )

    async def _settle(self, status: OperationStatus, spec: OperationSpec) -> None:
        timed_out = status.state == "timed_out"
        reported = _exit_code_of(status)
        exit_code = _resolve_stream_exit_code(reported, timed_out=timed_out)
        if timed_out:
            logger.error(
                "Stream timed out after %ds; reporting exit %s (operation=%s)",
                spec.timeout_seconds,
                exit_code,
                status.ref.operation_id,
            )
        self._last_exit_code = exit_code
        # THE MOMENT OF DEATH for the agent process itself - the shape that
        # takes a whole phase with tokens=0+0 and no terminal event (#1295,
        # #1319). The argv is the spec's, which carries no credential.
        self._last_signal_death = await capture_signal_death(list(spec.argv), exit_code)
        if self._last_signal_death is not None:
            logger.error(
                "Agent process died on a signal (operation=%s):\n%s",
                status.ref.operation_id,
                self._last_signal_death.describe(),
            )
        elif exit_code and exit_code != 0:
            logger.warning(
                "Stream process %s (operation=%s)",
                name_exit_status(exit_code),
                status.ref.operation_id,
            )
