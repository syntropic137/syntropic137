"""Forward reads of the whole store whose pages always fit the transport (#1640).

WHY. `read_all` pages by COUNT, but the gRPC client refuses a reply by BYTES:
anything over its receive limit (4 MiB by default) fails with
RESOURCE_EXHAUSTED. Event sizes vary by orders of magnitude (a start carrying
task text, a recorded transcript), so no page count is safe on every store:
500 events came to 12.4 MB on the selfhost VPS and `unapplied_starts` failed
on every interval, never getting past that page.

HOW. A `PageReader` asks for the count it was given. When a reply is refused
as too large it halves the count and asks again from the same position, down
to one event. The smaller size is kept for the rest of the reader's life, so
one scan pays for at most log2(page size) refusals however many pages it
reads; a fresh reader per scan starts large again. Shrinking skips nothing:
the retry starts where the refused read started.

ONE EVENT OVER THE LIMIT cannot be read by any page size. The reader raises
`OversizedEventError` naming the position rather than stepping past it,
because the event it cannot see may be exactly the one the caller is looking
for. The live subscription delivers events one per message under the same
limit, so such an event stalls the projections too; that is a store problem
an operator has to see, not one a reader should hide.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

import grpc
from event_sourcing.core.errors import EventStoreError

if TYPE_CHECKING:
    from event_sourcing import DomainEvent, EventEnvelope


class ReadsAllEvents(Protocol):
    async def read_all(
        self,
        from_global_nonce: int = 0,
        max_count: int = 100,
        forward: bool = True,
    ) -> tuple[list[EventEnvelope[DomainEvent]], bool, int]: ...


class OversizedEventError(EventStoreError):
    """The event at or after `from_global_nonce` alone exceeds the transport limit."""

    def __init__(self, from_global_nonce: int, original_error: Exception) -> None:
        super().__init__(
            f"the first event at or after global nonce {from_global_nonce} is larger than "
            "the client's gRPC receive limit, so no page size can read it (#1640)",
            original_error,
        )
        self.from_global_nonce = from_global_nonce


class PageReader:
    """Reads the store forward a page at a time; a page never exceeds what the transport carries."""

    def __init__(self, store: ReadsAllEvents, *, page_size: int) -> None:
        self._store = store
        self._page_size = page_size

    async def read(
        self, from_global_nonce: int, *, limit: int | None = None
    ) -> tuple[list[EventEnvelope[DomainEvent]], bool, int]:
        """One page from `from_global_nonce` (inclusive), at most `limit` events.

        Same contract as `read_all`: (events, is_end, next position).
        """
        while True:
            count = self._page_size if limit is None else min(self._page_size, limit)
            try:
                return await self._store.read_all(
                    from_global_nonce=from_global_nonce, max_count=count, forward=True
                )
            except EventStoreError as error:
                if not _too_large(error):
                    raise
                if count <= 1:
                    raise OversizedEventError(from_global_nonce, error) from error
                self._page_size = count // 2


def _too_large(error: BaseException) -> bool:
    """Whether the gRPC client refused the reply for its size.

    The SDK wraps the RpcError (`raise EventStoreError(...) from e`), so the
    status code is on the cause, not on the error itself.
    """
    cause = error.__cause__
    return isinstance(cause, grpc.RpcError) and cause.code() == grpc.StatusCode.RESOURCE_EXHAUSTED  # type: ignore[attr-defined]  # grpc.RpcError declares no code(); every client-side RpcError is a grpc.Call that does
