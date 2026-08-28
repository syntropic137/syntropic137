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

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from syn_domain.contexts.agent_sessions.delegate_usage import resolve_delegate_usage
from syn_domain.contexts.agent_sessions.domain.events.agent_observation import (
    ObservationType,
)
from syn_domain.contexts.agent_sessions.import_identity import platform_session_id_for
from syn_domain.contexts.agent_sessions.transcript_usage import (
    PricedUsage,
    RetryDisposition,
    UnpricedUsage,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from syn_domain.contexts.agent_sessions.delegate_usage import SessionStorePort
    from syn_domain.contexts.agent_sessions.transcript_usage import UsageResult

__all__ = [
    "DelegateImport",
    "ImportedDelegate",
    "ObservationWriter",
    "import_phase_delegates",
]


class ObservationWriter(Protocol):
    """The observability lane's write side, narrowed to what this needs."""

    async def record_observation(
        self,
        session_id: str,
        observation_type: str,
        data: dict[str, object],
        execution_id: str | None = None,
        phase_id: str | None = None,
        workspace_id: str | None = None,
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


def _observation_for(usage: UsageResult) -> tuple[dict[str, object], bool, str | None]:
    """Turn one delegate's usage into the payload to record."""
    if isinstance(usage, PricedUsage):
        # The four buckets are disjoint by construction, so they map straight
        # across. Any summing here would be a second home for the
        # double-counting bug this module exists to avoid.
        return (
            {
                "input_tokens": usage.uncached_input_tokens,
                "output_tokens": usage.output_tokens,
                "cache_creation_tokens": usage.cache_creation_tokens,
                "cache_read_tokens": usage.cache_read_tokens,
                "model": usage.model,
                "delegated": True,
            },
            True,
            None,
        )

    reason = usage.reason if isinstance(usage, UnpricedUsage) else "transcript carried no usage"
    # Zeroes WITH a reason, never an omission. A delegate that is present and
    # unpriceable has to stay visible; dropping it makes it identical to a
    # delegate that never ran, which is the invisibility this issue is about.
    return (
        {
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_creation_tokens": 0,
            "cache_read_tokens": 0,
            "model": None,
            "delegated": True,
            "unpriced_reason": reason,
        },
        False,
        reason,
    )


def _is_retryable(usage: UsageResult) -> bool:
    """Whether asking the store again could change this answer."""
    return isinstance(usage, UnpricedUsage) and usage.retry is not RetryDisposition.PERMANENT


async def import_phase_delegates(
    store: SessionStorePort,
    writer: ObservationWriter,
    *,
    leader_native_session_id: str | None,
    captured_session_ids: Sequence[str],
    execution_id: str,
    phase_id: str,
    workspace_id: str | None = None,
    attempts_remaining: int,
) -> DelegateImport:
    """Price every captured session except the leader's.

    Args:
        store: Where delegated transcripts are read back from.
        writer: The observability lane's write side.
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

        data, priced, reason = _observation_for(usage)
        # uuid5 of the harness id, so a re-run addresses the SAME session
        # rather than minting a second one carrying the same tokens. That is
        # what makes this safe to retry and safe to resume after a crash.
        platform_id = platform_session_id_for(harness_id)
        await writer.record_observation(
            session_id=platform_id,
            observation_type=ObservationType.TOKEN_USAGE.value,
            data=data,
            execution_id=execution_id,
            phase_id=phase_id,
            workspace_id=workspace_id,
        )
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
