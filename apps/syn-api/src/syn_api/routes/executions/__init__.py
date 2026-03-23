"""Execution route package — queries, commands, and control.

Creates a combined router and re-exports service functions for test access.
"""

from __future__ import annotations

from fastapi import APIRouter

from .commands import execute
from .commands import router as commands_router
from .control import cancel, get_state, inject, pause, resume
from .control import router as control_router
from .queries import get, get_detail, list_, list_active
from .queries import router as queries_router

router = APIRouter()
router.include_router(queries_router)
router.include_router(commands_router)
router.include_router(control_router)

# Re-export service functions so callers can do:
#   from syn_api.routes.executions import list_, execute, pause, ...
__all__ = [
    "cancel",
    "execute",
    "get",
    "get_detail",
    "get_state",
    "inject",
    "list_",
    "list_active",
    "pause",
    "resume",
    "router",
]
