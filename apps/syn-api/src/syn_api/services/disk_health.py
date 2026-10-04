"""The /health ``disk`` block: free space on the workspace volume (#1560)."""

from __future__ import annotations

import logging

from syn_api.services.degraded_reasons import DegradedReason
from syn_api.types import DiskSpaceHealth

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
