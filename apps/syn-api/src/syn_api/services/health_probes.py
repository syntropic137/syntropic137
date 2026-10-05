"""Per-instance probes that /health reports and that need no lifecycle state.

Kept apart from ``lifecycle`` so ``health_check`` there only assembles the
response; each probe here answers one question and never raises.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from syn_shared.codex_auth_status import CodexAuthStatus

logger = logging.getLogger(__name__)


def describe_codex_auth_health() -> CodexAuthStatus | None:
    """How fresh this instance's codex credential is, or None if it cannot be said.

    WHY HERE: a stale codex credential is invisible until a phase fails, and the
    failure names no credential. Every instance holds its own copy and expires
    independently, so this has to be reported per instance rather than centrally,
    which is exactly what a health endpoint is for.

    Never raises. A freshness hint that can take /health down is worse than no
    hint, so any failure degrades to omitting the block.
    """
    try:
        from syn_shared.codex_auth_status import describe_codex_auth
        from syn_shared.settings import get_settings

        secret = get_settings().codex_auth_json
        return describe_codex_auth(secret.get_secret_value() if secret else None)
    except Exception:
        logger.debug("codex auth freshness probe failed", exc_info=True)
        return None
