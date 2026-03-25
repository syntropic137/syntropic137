"""GitHub webhook route package.

Provides the HTTP endpoint for receiving GitHub webhooks, signature
verification, trigger evaluation, and acknowledgment posting.  Also
exposes service functions for querying installations and repositories.
"""

from __future__ import annotations

from fastapi import APIRouter

from syn_api.routes.webhooks.endpoint import router as endpoint_router
from syn_api.routes.webhooks.processing import verify_and_process_webhook
from syn_api.routes.webhooks.services import get_installation, list_repos

router = APIRouter()
router.include_router(endpoint_router)

__all__ = [
    "get_installation",
    "list_repos",
    "router",
    "verify_and_process_webhook",
]
