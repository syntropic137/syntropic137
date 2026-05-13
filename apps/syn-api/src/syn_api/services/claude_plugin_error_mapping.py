"""Map typed claude-plugin errors to HTTP responses (issue #726).

Each ``ClaudePluginError`` subclass carries a stable ``error_code`` class
attribute. The API layer surfaces those codes as HTTP 422 responses so the
CLI and dashboard can branch on the code without string-sniffing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import HTTPException

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration._shared.claude_plugin_errors import (
        ClaudePluginError,
    )


def http_exception_for_claude_plugin_error(exc: ClaudePluginError) -> HTTPException:
    """Convert a ``ClaudePluginError`` into a 422 ``HTTPException``.

    Why 422 (not 400 or 502): the ref itself is the user's input, but
    "unreachable" is upstream. Both shapes are about the *meaning* of the
    request being unprocessable in this context, which 422 captures cleanly.
    """
    detail: dict[str, str] = {
        "error_code": exc.error_code,
        "message": str(exc),
    }
    # Attach optional context fields when present so CLI/dashboard can render
    # actionable messages without re-parsing the human-readable string.
    source_url = getattr(exc, "source_url", None)
    if isinstance(source_url, str) and source_url:
        detail["source_url"] = source_url
    version = getattr(exc, "version", None)
    if isinstance(version, str) and version:
        detail["version"] = version
    return HTTPException(status_code=422, detail=detail)
