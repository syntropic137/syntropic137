"""Organization domain model."""

from dataclasses import dataclass


@dataclass(frozen=True)
class HandlerResult:
    """Discriminated result for manage handlers.

    Handlers return:
    - ``HandlerResult(success=True)`` on success
    - ``None`` when the aggregate is not found
    - ``HandlerResult(success=False, error=...)`` when a domain rule is violated
    """

    success: bool
    error: str = ""
