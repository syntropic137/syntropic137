"""Map typed skill errors to HTTP responses (issue #772).

Mirrors ``claude_plugin_error_mapping.py``. Each ``SkillError`` subclass
carries a stable ``error_code`` class attribute surfaced as an HTTP 422
response so the CLI and dashboard can branch on the code without
string-sniffing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import HTTPException

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration._shared.skill_errors import SkillError


def http_exception_for_skill_error(exc: SkillError) -> HTTPException:
    """Convert a ``SkillError`` into a 422 ``HTTPException``.

    Why 422: the API does no git work, so the error taxonomy is purely
    about request semantics -- manifest-missing, manifest-invalid, or an
    unsafe file path in the uploaded tree. All mean the request itself is
    unprocessable in this state, which 422 captures cleanly.
    """
    detail: dict[str, str] = {
        "error_code": exc.error_code,
        "message": str(exc),
    }
    source_url = getattr(exc, "source_url", None)
    if isinstance(source_url, str) and source_url:
        detail["source_url"] = source_url
    version = getattr(exc, "version", None)
    if isinstance(version, str) and version:
        detail["version"] = version
    skill_name = getattr(exc, "skill_name", None)
    if isinstance(skill_name, str) and skill_name:
        detail["skill_name"] = skill_name
    return HTTPException(status_code=422, detail=detail)
