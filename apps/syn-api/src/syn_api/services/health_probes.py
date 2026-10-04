"""Probes behind optional /health blocks.

Each one never raises: a probe that could take /health down is worse than an
omitted block, so any failure degrades to None. Moved out of lifecycle.py,
which owns startup and shutdown, when the disk probe (#1560) arrived.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from syn_api.services.degraded_reasons import DegradedReason
from syn_api.types import DiskSpaceHealth

if TYPE_CHECKING:
    from syn_shared.codex_auth_status import CodexAuthStatus

logger = logging.getLogger(__name__)


def describe_disk_health() -> tuple[DiskSpaceHealth | None, list[DegradedReason]]:
    """Free space on the workspace volume, judged by the admission gate's own guard.

    The SAME guard admission refuses with, so a refused execution is always
    explained by a ``critical`` block here. Never raises: a probe that could
    take /health down is worse than an omitted block.
    """
    try:
        from syn_api._wiring_admission import get_disk_space_guard

        check = get_disk_space_guard().check()
    except Exception:
        logger.warning("disk space probe could not be built", exc_info=True)
        return None, []
    health = DiskSpaceHealth(
        path=check.path,
        state=check.state.value,
        free_percent=None if check.usage is None else round(check.usage.free_percent, 2),
        free_bytes=None if check.usage is None else check.usage.free_bytes,
        degraded_below_percent=check.degraded_below_percent,
        refuse_admission_below_percent=check.refuse_admission_below_percent,
    )
    return health, [DegradedReason.DISK_SPACE] if check.is_degraded else []


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
