"""Shared error types for workspace backend adapters (issue #771 item 7).

`WorkspaceProvisionError` originally lived only in
`syn_adapters.workspace_backends.agentic.adapter` (the Docker-backed
provider). It lives here so error-mapping layers downstream
(`_fail_execution`, `syn execution show`) have one type to match against
instead of a bare `RuntimeError`, importable without pulling in the
agentic adapter module; `agentic/adapter.py` re-exports it for backward
compatibility.
"""

from __future__ import annotations


class WorkspaceProvisionError(RuntimeError):
    """Raised when workspace provisioning fails or is misconfigured.

    Wraps the underlying error (or a misconfiguration message, e.g. a
    disabled feature flag or an unavailable provider) with enough context
    so downstream error-mapping layers can surface an actionable message
    instead of "Unknown error".
    """


__all__ = ["WorkspaceProvisionError"]
