"""Current whole-object policy, independent of frozen inventory membership."""

from typing import Literal, Protocol

from .SessionCaptureCatalogPort import CataloguedCapture

BodyTombstone = Literal["expired", "deleted"]
"""Why exact bytes may no longer be served: retention expiry, or deletion/retraction."""


class SessionTranscriptAccessPort(Protocol):
    async def require_read(self, capture: CataloguedCapture) -> None:
        """Authorize the complete revision for the current caller, or raise.

        Implementations must check current deletion and access policy for all
        shared memberships. Visibility of capture.run alone is insufficient.
        A retained inventory row never grants permission to read archived bytes.
        """
        ...

    async def tombstone(self, capture: CataloguedCapture) -> BodyTombstone | None:
        """Durable body tombstone for these exact bytes, including pending requests.

        A requested but not yet executed deletion already withholds the body, so
        no read can observe bytes the owner asked to remove.
        """
        ...
