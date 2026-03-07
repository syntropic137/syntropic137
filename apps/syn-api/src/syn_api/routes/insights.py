"""Global insight API endpoints — thin wrapper over v1."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter

import syn_api.v1.insights as insight_ops

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/insights", tags=["insights"])


@router.get("/overview")
async def get_global_overview() -> dict[str, Any]:
    """Get global overview of all systems and repos."""
    return await insight_ops.get_global_overview()


@router.get("/cost")
async def get_global_cost() -> dict[str, Any]:
    """Get global cost breakdown across all repos."""
    return await insight_ops.get_global_cost()
