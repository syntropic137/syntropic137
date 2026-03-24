"""Tenant-level token operations for admin/monitoring.

Extracted from TokenVendingService to reduce module complexity.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from syn_tokens.models import ScopedToken
    from syn_tokens.token_stores import TokenStore

logger = logging.getLogger(__name__)


async def get_tokens_by_tenant(
    store: TokenStore,
    tenant_id: str,
) -> list[ScopedToken]:
    """Get all active tokens for a tenant.

    Note: This requires scanning, which is O(n). For production,
    consider adding a tenant index to the store.

    Args:
        store: Token storage backend.
        tenant_id: The tenant ID to query.

    Returns:
        List of active tokens for this tenant.
    """
    from syn_tokens.token_stores import InMemoryTokenStore

    if isinstance(store, InMemoryTokenStore):
        return [
            token
            for token in store._tokens.values()
            if token.tenant_id == tenant_id and not token.is_expired
        ]
    # Redis implementation would need SCAN with pattern matching
    logger.warning("get_tokens_by_tenant not fully implemented for Redis store")
    return []


async def revoke_tokens_for_tenant(
    store: TokenStore,
    tenant_id: str,
) -> int:
    """Revoke all tokens for a tenant.

    Args:
        store: Token storage backend.
        tenant_id: The tenant to revoke tokens for.

    Returns:
        Number of tokens revoked.
    """
    tokens = await get_tokens_by_tenant(store, tenant_id)
    count = 0

    for token in tokens:
        if await store.delete(token.token_id):
            count += 1

    if count > 0:
        logger.info(
            "Tokens revoked for tenant (tenant_id=%s, count=%d)",
            tenant_id,
            count,
        )

    return count
