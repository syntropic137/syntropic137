"""Save a session aggregate so a concurrent writer never erases a command (#1398).

Invocation decisions (first binding, contradicting claim, lifecycle outcome)
are taken against the aggregate the caller loaded. When another writer
advanced the stream first, the expected-version check rejects the save and
the command's fact would otherwise be lost: two writers each proposing a
first binding would leave one claim nowhere, instead of the conflict event
that makes coverage conflicting. So a rejected save reloads the stream and
re-decides every pending command against current state, then saves again.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from event_sourcing import ConcurrencyConflictError, StreamAlreadyExistsError

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

#: Bounded: each retry re-reads the stream, so only a writer that keeps winning
#: the race exhausts it, and then the conflict surfaces instead of looping.
SAVE_ATTEMPTS = 3


class _Store[A](Protocol):
    async def get_by_id(self, aggregate_id: str) -> A | None: ...
    async def save(self, aggregate: A) -> None: ...


async def save_reapplying[A](
    repository: _Store[A],
    aggregate_id: str,
    aggregate: A,
    pending: Sequence[Callable[[A], None]],
    *,
    attempts: int = SAVE_ATTEMPTS,
) -> A:
    """Save ``aggregate``; on a version conflict reload and reapply ``pending``.

    ``pending`` are the commands already applied to ``aggregate`` since it was
    last persisted, in order. Returns the aggregate that was saved, which is a
    fresh reload whenever a retry happened. A new stream colliding with an
    existing one is not a stale read and is never retried.
    """
    current = aggregate
    for attempt in range(1, attempts + 1):
        try:
            await repository.save(current)
        except StreamAlreadyExistsError:
            raise
        except ConcurrencyConflictError:
            if attempt == attempts:
                raise
            reloaded = await repository.get_by_id(aggregate_id)
            if reloaded is None:
                raise
            for command in pending:
                command(reloaded)
            current = reloaded
        else:
            return current
    raise AssertionError("unreachable: the last attempt returns or raises")
