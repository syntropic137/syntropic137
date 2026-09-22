"""Current whole-object policy, independent of frozen inventory membership."""

from typing import Protocol

from .SessionCaptureCatalogPort import CataloguedCapture


class SessionTranscriptAccessPort(Protocol):
    async def require_read(self, capture: CataloguedCapture) -> None:
        """Authorize the complete revision for the current caller, or raise.

        Implementations must check current deletion and access policy for all
        shared memberships. Visibility of capture.run alone is insufficient.
        A retained inventory row never grants permission to read archived bytes.
        """
        ...
