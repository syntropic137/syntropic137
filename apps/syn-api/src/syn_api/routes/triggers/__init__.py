"""Trigger management route package.

Provides service functions and HTTP endpoints for GitHub event trigger
registration, management, and history queries.
"""

from __future__ import annotations

from fastapi import APIRouter

from syn_api.routes.triggers.commands import (
    delete_trigger,
    disable_triggers,
    enable_preset,
    pause_trigger,
    register_trigger,
    resume_trigger,
)
from syn_api.routes.triggers.commands import router as commands_router
from syn_api.routes.triggers.queries import (
    get_trigger,
    get_trigger_history,
    list_triggers,
)
from syn_api.routes.triggers.queries import router as queries_router

router = APIRouter()
router.include_router(queries_router)
router.include_router(commands_router)

__all__ = [
    "delete_trigger",
    "disable_triggers",
    "enable_preset",
    "get_trigger",
    "get_trigger_history",
    "list_triggers",
    "pause_trigger",
    "register_trigger",
    "resume_trigger",
    "router",
]
