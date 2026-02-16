"""Authentication context for API operations.

AuthContext is an optional parameter accepted by all v1 functions.
When None (the default), operations run without authorization checks.
Future phases will wire this to real identity providers.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AuthContext:
    """Authentication context for API calls.

    Attributes:
        user_id: Authenticated user identifier.
        tenant_id: Optional tenant for multi-tenant isolation.
        roles: Set of role names for authorization checks.
    """

    user_id: str
    tenant_id: str | None = None
    roles: frozenset[str] = frozenset()
