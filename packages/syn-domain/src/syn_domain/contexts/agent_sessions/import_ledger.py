"""What this execution has already billed, per harness session (#933, #936).

The platform session id is a pure function of the harness session id, with no
execution or phase in it. That gives stable IDENTITY and nothing more: writes
land in an append-only store with no uniqueness key, and the cost queries SUM.
So the same harness session captured by two phases, or one phase imported twice
after a crash, bills twice under a single session id.

The two issues are one defect. #933 sees it as "re-import doubles"; #936 sees it
as "phase 2 recounts what phase 1 billed". Both are the missing record of what
has already been charged.

WHY A HIGH-WATER MARK RATHER THAN A SEEN-SET. A resumed harness session keeps
ONE cumulative transcript: phase 1 sees 25 output tokens, phase 2 sees 40 -
the same 25 plus 15 of new work. A seen-set would skip phase 2 entirely and
lose the 15; billing the whole 40 again double-charges the first 25. Recording
what was already billed and charging the DELTA is the only answer that is right
in both directions.

A transcript that SHRANK is not a refund. It means the store returned a
different or truncated document, and inventing a negative charge to reconcile
is worse than declining to bill: the delta is clamped at zero and the reason is
recorded.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from syn_domain.contexts.agent_sessions.transcript_usage import PricedUsage

__all__ = ["BilledUsage", "ImportLedger", "ImportLedgerPort", "InMemoryImportLedger"]


@dataclass(frozen=True)
class BilledUsage:
    """The four buckets already charged for one harness session."""

    uncached_input_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    output_tokens: int = 0

    @classmethod
    def of(cls, usage: PricedUsage) -> BilledUsage:
        return cls(
            uncached_input_tokens=usage.uncached_input_tokens,
            cache_read_tokens=usage.cache_read_tokens,
            cache_creation_tokens=usage.cache_creation_tokens,
            output_tokens=usage.output_tokens,
        )

    @property
    def is_nothing(self) -> bool:
        return not (
            self.uncached_input_tokens
            or self.cache_read_tokens
            or self.cache_creation_tokens
            or self.output_tokens
        )


class ImportLedgerPort(Protocol):
    """Durable record of what an execution has already billed.

    A Protocol because the real one must outlive the process - a crash between
    the write and phase completion is precisely the case #933 is about, and an
    in-memory ledger cannot survive it. The in-memory implementation below is
    for tests and for a single-process import; production must supply a durable
    one or the guarantee is only as good as the process.
    """

    async def already_billed(self, execution_id: str, harness_session_id: str) -> BilledUsage:
        """What has been charged so far, or zeroes if nothing has."""
        ...

    async def record_billed(
        self, execution_id: str, harness_session_id: str, billed: BilledUsage
    ) -> None:
        """Set the high-water mark for this session to the CUMULATIVE total."""
        ...


@dataclass
class InMemoryImportLedger(ImportLedgerPort):
    """Process-local ledger. Correct within one process, lost on restart."""

    _marks: dict[tuple[str, str], BilledUsage] = field(default_factory=dict)

    async def already_billed(self, execution_id: str, harness_session_id: str) -> BilledUsage:
        return self._marks.get((execution_id, harness_session_id), BilledUsage())

    async def record_billed(
        self, execution_id: str, harness_session_id: str, billed: BilledUsage
    ) -> None:
        self._marks[(execution_id, harness_session_id)] = billed


@dataclass(frozen=True)
class ImportLedger:
    """Turns a cumulative transcript into the part not yet billed."""

    port: ImportLedgerPort

    async def unbilled_delta(
        self, execution_id: str, harness_session_id: str, usage: PricedUsage
    ) -> tuple[BilledUsage, str | None]:
        """The portion of ``usage`` this execution has not yet been charged for.

        Returns the delta and, when there is something odd about it, a reason.
        A zero delta with no reason means the transcript is unchanged since the
        last import and there is genuinely nothing to bill.
        """
        previous = await self.port.already_billed(execution_id, harness_session_id)
        cumulative = BilledUsage.of(usage)

        def _delta(now: int, before: int) -> tuple[int, bool]:
            # Clamped: a transcript cannot un-spend tokens, so a negative means
            # the store returned a different or truncated document. Charging a
            # negative to reconcile would be inventing a refund.
            return (now - before, False) if now >= before else (0, True)

        pairs = [
            _delta(cumulative.uncached_input_tokens, previous.uncached_input_tokens),
            _delta(cumulative.cache_read_tokens, previous.cache_read_tokens),
            _delta(cumulative.cache_creation_tokens, previous.cache_creation_tokens),
            _delta(cumulative.output_tokens, previous.output_tokens),
        ]
        shrank = any(flag for _, flag in pairs)
        delta = BilledUsage(*(value for value, _ in pairs))

        reason = None
        if shrank:
            reason = (
                f"transcript for {harness_session_id} is smaller than what was "
                "already billed; the store returned a different or truncated document"
            )
        return delta, reason

    async def commit(self, execution_id: str, harness_session_id: str, usage: PricedUsage) -> None:
        """Move the high-water mark to this transcript's CUMULATIVE total.

        Cumulative, not the delta: the mark answers "how much of this session
        has been charged", and a later import compares its own cumulative
        figure against it.
        """
        await self.port.record_billed(execution_id, harness_session_id, BilledUsage.of(usage))
