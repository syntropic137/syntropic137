"""Importing a phase's delegated sessions by lookup, not by inference (#895).

A phase produces one session per agent that ran in it. The platform priced
exactly one of them - its own - and the filesystem sweep reports all of them,
keyed by the id each HARNESS chose. The whole problem is telling the one
already priced from the ones priced nowhere.

An earlier design INFERRED that by matching agent names against the phase's
declared provider. It worked, and it had a hole exactly where it mattered: two
sessions carrying the same agent name are indistinguishable, so a claude phase
delegating to claude - the most common shape there is - classified both as
unattributable and priced neither.

This does not infer. The stream processors read the leader's own session id off
its output as the run happens (claude announces ``session_id``, codex announces
``thread_id`` on ``thread.started``), so by the time the sweep is read the
leader is KNOWN. Import is then set subtraction: everything captured, minus the
one id we already billed. Agent names never enter into it, and claude
delegating to claude is no harder than claude delegating to codex.

Two invariants remain, both about failing visibly.

THE LEADER IS NEVER WRITTEN. It is already priced. A second write would
overcount, and an overcount is the failure nobody reports: an undercount looks
like a missing delegate, while an overcount just looks like expensive work.

A LEADER MISSING FROM THE SWEEP IS AN ERROR, NOT A SKIP. If the leader's id is
not among the captured ids, the identity assumption this module rests on has
broken - a harness changed what it announces, or the sweep read a different
partition. Importing everything would then bill the leader twice. Importing
nothing would silently drop real delegates. So it does neither: it refuses and
says so.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Protocol

from syn_domain.contexts.agent_sessions.delegate_usage import resolve_delegate_usage
from syn_domain.contexts.agent_sessions.import_identity import platform_session_id_for
from syn_domain.contexts.agent_sessions.import_ledger import ImportLedger
from syn_domain.contexts.agent_sessions.transcript_usage import (
    PricedUsage,
    RetryDisposition,
    UnpricedUsage,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from syn_domain.contexts.agent_sessions.delegate_usage import SessionStorePort
    from syn_domain.contexts.agent_sessions.import_ledger import ImportLedgerPort
    from syn_domain.contexts.agent_sessions.transcript_usage import UsageResult

__all__ = [
    "DelegateImport",
    "DelegateUsageRecorder",
    "ImportedDelegate",
    "import_phase_delegates",
]


class DelegateUsageRecorder(Protocol):
    """Where a recovered delegate cost goes.

    Deliberately NOT the observability writer's own signature. That port takes
    an untyped payload dict, and a domain module that builds one has to know
    the observation's field names - so a rename in the telemetry schema would
    silently stop pricing delegates while every test kept passing.

    This asks for the numbers instead and lets the adapter shape them.
    """

    async def record_delegate_usage(
        self,
        *,
        session_id: str,
        usage: PricedUsage | None,
        unpriced_reason: str | None,
        execution_id: str,
        phase_id: str,
        workspace_id: str | None,
    ) -> None: ...


@dataclass(frozen=True)
class ImportedDelegate:
    """One delegate as this module left it.

    ``priced`` describes the WRITE, not the delegate: it says whether real
    token counts went in. Anything totalling recovered spend must read it
    rather than assume every entry carried numbers.
    """

    harness_session_id: str
    platform_session_id: str
    priced: bool
    reason: str | None = None


@dataclass(frozen=True)
class DelegateImport:
    """What one import attempt did, and whether the phase may finalise."""

    imported: tuple[ImportedDelegate, ...]
    retry_ids: tuple[str, ...]
    """Delegates whose store read could still succeed on a later attempt."""

    attempts_remaining: int
    leader_missing_from_sweep: bool = False
    """The identity assumption broke. Nothing was written; see module docstring."""

    @property
    def may_finalise(self) -> bool:
        """False only while a retry could still add a delegate.

        A phase must not emit its cost while this is False: doing so finalises
        a total already known to be short, and afterwards nothing distinguishes
        it from a complete one.
        """
        if self.leader_missing_from_sweep:
            return False
        return not self.retry_ids or self.attempts_remaining <= 0

    @property
    def exhausted(self) -> bool:
        """Finalising with a KNOWN gap, which is not the same as complete."""
        return bool(self.retry_ids) and self.attempts_remaining <= 0


def _split(usage: UsageResult) -> tuple[PricedUsage | None, str | None]:
    """Separate a priced result from an unpriceable one and its reason.

    An unpriceable delegate keeps its reason and is still recorded. Dropping it
    would make it identical to a delegate that never ran, which is exactly the
    invisibility this issue exists to end.
    """
    if isinstance(usage, PricedUsage):
        return usage, None
    if isinstance(usage, UnpricedUsage):
        return None, usage.reason
    return None, "transcript carried no usage"


def _is_retryable(usage: UsageResult) -> bool:
    """Whether asking the store again could change this answer."""
    return isinstance(usage, UnpricedUsage) and usage.retry is not RetryDisposition.PERMANENT


async def import_phase_delegates(
    store: SessionStorePort,
    recorder: DelegateUsageRecorder,
    *,
    leader_native_session_id: str | None,
    captured_session_ids: Sequence[str],
    execution_id: str,
    phase_id: str,
    workspace_id: str | None = None,
    attempts_remaining: int,
    ledger: ImportLedgerPort | None = None,
) -> DelegateImport:
    """Price every captured session except the leader's.

    Args:
        store: Where delegated transcripts are read back from.
        recorder: Where a recovered delegate cost is recorded.
        leader_native_session_id: The id the phase's own harness announced on
            its stream. ``None`` when the stream never announced one, in which
            case nothing is imported - see below.
        captured_session_ids: Every session id the sweep confirmed, as the
            harnesses key them.
        attempts_remaining: Retry budget left. Zero or fewer makes this the
            last word, and any still-unreadable delegate becomes a named gap.
    """
    captured = tuple(dict.fromkeys(i for i in captured_session_ids if i and i.strip()))
    if not captured:
        return DelegateImport(imported=(), retry_ids=(), attempts_remaining=attempts_remaining)

    if leader_native_session_id is None or leader_native_session_id not in captured:
        # Refusing, not guessing. Without a known leader every id is a
        # candidate: importing all of them bills the leader twice, importing
        # none silently drops real delegates. Both are worse than saying so.
        return DelegateImport(
            imported=(),
            retry_ids=(),
            attempts_remaining=attempts_remaining,
            leader_missing_from_sweep=True,
        )

    imported: list[ImportedDelegate] = []
    retry_ids: list[str] = []
    for harness_id in captured:
        if harness_id == leader_native_session_id:
            continue

        usage = await resolve_delegate_usage(store, harness_id)
        if _is_retryable(usage) and attempts_remaining > 0:
            # Held back rather than written as a zero. Writing it now would
            # finalise a delegate the very next attempt could have priced.
            retry_ids.append(harness_id)
            continue

        priced_usage, reason = _split(usage)

        # What this execution has NOT already been charged for. A harness
        # session can be captured by more than one phase - it is resumed, and
        # its transcript is CUMULATIVE - and a phase can be imported twice
        # after a crash. Both write under the same derived session id, and the
        # cost queries sum. Charging the delta is what makes those safe
        # (#933, #936).
        if ledger is not None and priced_usage is not None:
            book = ImportLedger(ledger)
            delta, ledger_reason = await book.unbilled_delta(execution_id, harness_id, priced_usage)
            if ledger_reason:
                reason = ledger_reason
                priced_usage = None
            elif delta.is_nothing:
                # Already billed in full and the transcript has not moved.
                # Recording it again is the double count.
                continue
            else:
                priced_usage = replace(
                    priced_usage,
                    uncached_input_tokens=delta.uncached_input_tokens,
                    cache_read_tokens=delta.cache_read_tokens,
                    cache_creation_tokens=delta.cache_creation_tokens,
                    output_tokens=delta.output_tokens,
                )
        # uuid5 of the harness id, so a re-run addresses the SAME session
        # rather than minting a second one.
        #
        # That is NOT full idempotency, and this comment used to claim it was.
        # `agent_events` is append-only with no uniqueness constraint, so a
        # second import writes a second pair of rows under the same session id
        # and the cost queries SUM them. Same id, doubled tokens (#933).
        #
        # What keeps it correct today: exactly one import per phase. The
        # retry budget is spent (attempts_remaining=0) and the finalise and
        # teardown paths are mutually exclusive, since finalisation pops the
        # workspace context manager before teardown iterates. A crash between
        # the write and the phase completing is the case that is NOT covered.
        platform_id = platform_session_id_for(harness_id)
        await recorder.record_delegate_usage(
            session_id=platform_id,
            usage=priced_usage,
            unpriced_reason=reason,
            execution_id=execution_id,
            phase_id=phase_id,
            workspace_id=workspace_id,
        )
        priced = priced_usage is not None
        if ledger is not None and priced and isinstance(usage, PricedUsage):
            # The CUMULATIVE figure, not the delta just written: the mark
            # answers "how much of this session has been charged", and the next
            # import compares its own cumulative total against it.
            #
            # AFTER the write, deliberately. A mark that ran ahead of what was
            # actually recorded would make a crash between the two look like
            # spend that had already been billed, and it would never be.
            await ImportLedger(ledger).commit(execution_id, harness_id, usage)
        if _is_retryable(usage):
            retry_ids.append(harness_id)
        imported.append(
            ImportedDelegate(
                harness_session_id=harness_id,
                platform_session_id=platform_id,
                priced=priced,
                reason=reason,
            )
        )

    return DelegateImport(
        imported=tuple(imported),
        retry_ids=tuple(retry_ids),
        attempts_remaining=attempts_remaining,
    )
