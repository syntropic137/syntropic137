"""Runtime feature flags (#105, ADR-016).

The dashboard ships as one image for everyone, so it cannot learn at build
time which optional features an operator has switched on: a Vite env var
would bake the answer into the bundle and make enabling a feature a rebuild
rather than one .env line plus a restart. It asks here instead, at runtime.

Unauthenticated-adjacent by nature: the response says only which features
exist and whether they are on, never any configuration behind them.
"""

from __future__ import annotations

from fastapi import APIRouter

from syn_api.types import FeaturesResponse

router = APIRouter(prefix="/features", tags=["features"])


@router.get("", response_model=FeaturesResponse)
async def get_features() -> FeaturesResponse:
    """Report which optional features are enabled on this deployment."""
    from syn_api.services import ui_feedback

    return FeaturesResponse(ui_feedback=ui_feedback.is_enabled())
