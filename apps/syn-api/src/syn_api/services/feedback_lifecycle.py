"""Optional feedback service startup and shutdown hooks."""

from __future__ import annotations

from syn_shared.settings import get_settings


async def init_ui_feedback(_state: object) -> None:
    """Apply the feedback schema only when an operator enables the feature."""
    if not get_settings().syn_ui_feedback_enabled:
        return

    from syn_api.services import ui_feedback

    await ui_feedback.connect()


async def shutdown_ui_feedback(_state: object) -> None:
    """Close the feedback pool when it was enabled."""
    if not get_settings().syn_ui_feedback_enabled:
        return

    from syn_api.services import ui_feedback

    await ui_feedback.disconnect()
