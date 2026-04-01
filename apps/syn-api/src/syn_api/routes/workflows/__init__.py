"""Workflow TEMPLATE API — route package.

Creates the ``/workflows`` router and re-exports service functions
so that callers can do::

    from syn_api.routes.workflows import router
    from syn_api.routes.workflows import list_workflows, get_workflow
"""

from __future__ import annotations

from fastapi import APIRouter

from syn_api.routes.workflows.commands import create_workflow, delete_workflow, validate_yaml
from syn_api.routes.workflows.commands import router as commands_router
from syn_api.routes.workflows.queries import (
    export_workflow,
    get_workflow,
    list_workflows,
)
from syn_api.routes.workflows.queries import (
    router as queries_router,
)

router = APIRouter()
router.include_router(queries_router)
router.include_router(commands_router)

__all__ = [
    "create_workflow",
    "delete_workflow",
    "export_workflow",
    "get_workflow",
    "list_workflows",
    "router",
    "validate_yaml",
]
