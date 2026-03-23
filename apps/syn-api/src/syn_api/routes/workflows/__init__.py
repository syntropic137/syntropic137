"""Workflow TEMPLATE API — route package.

Creates the ``/workflows`` router and re-exports service functions
so that callers can do::

    from syn_api.routes.workflows import router
    from syn_api.routes.workflows import list_workflows, get_workflow
"""

from __future__ import annotations

from fastapi import APIRouter

from syn_api.routes.workflows.commands import create_workflow, validate_yaml
from syn_api.routes.workflows.queries import (
    get_workflow,
    list_workflows,
    router as queries_router,
)

router = APIRouter()
router.include_router(queries_router)

__all__ = [
    "create_workflow",
    "get_workflow",
    "list_workflows",
    "router",
    "validate_yaml",
]
