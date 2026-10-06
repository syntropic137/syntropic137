"""ExecutionRequest value objects (#1557)."""

from __future__ import annotations

#: Prefixes a request's aggregate id. A request may never share its
#: execution's id: the event store keys a stream by aggregate id alone, so the
#: request would become version 1 of the execution's stream and the start's
#: NoStream write would be refused as a duplicate dispatch (see
#: `ExecutionRequestAggregate`'s module docstring).
EXECUTION_REQUEST_ID_PREFIX = "request-"


def execution_request_id(execution_id: str) -> str:
    """The aggregate id of the request that names ``execution_id``."""
    return f"{EXECUTION_REQUEST_ID_PREFIX}{execution_id}"
