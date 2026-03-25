"""Unit tests for webhook event handlers."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from syn_api.routes.webhooks.handlers import (
    _classify_trigger_results,
    _evaluate_triggers,
    _handle_installation_event,
)

# --- _handle_installation_event ---


@pytest.mark.anyio
async def test_handle_installation_event_created() -> None:
    mock_projection = AsyncMock()
    mock_event_cls = MagicMock()
    mock_event_cls.from_webhook.return_value = MagicMock()

    with (
        patch(
            "syn_api.routes.webhooks.handlers.get_installation_projection",
            return_value=mock_projection,
            create=True,
        ),
        patch(
            "syn_domain.contexts.github.domain.events.AppInstalledEvent",
            mock_event_cls,
        ),
        patch(
            "syn_domain.contexts.github.slices.get_installation.projection.get_installation_projection",
            return_value=mock_projection,
        ),
    ):
        await _handle_installation_event("installation", "created", {"installation": {"id": 1}})

    mock_projection.handle_app_installed.assert_awaited_once()


@pytest.mark.anyio
async def test_handle_installation_unrelated_event_noop() -> None:
    # Non-installation event should return immediately
    await _handle_installation_event("push", "completed", {})


@pytest.mark.anyio
async def test_handle_installation_exception_swallowed() -> None:
    with (
        patch(
            "syn_domain.contexts.github.domain.events.AppInstalledEvent",
            side_effect=RuntimeError("boom"),
        ),
        patch(
            "syn_domain.contexts.github.slices.get_installation.projection.get_installation_projection",
            return_value=AsyncMock(),
        ),
    ):
        # Should not raise
        await _handle_installation_event("installation", "created", {})


# --- _classify_trigger_results ---


def test_classify_trigger_results_mixed() -> None:
    with patch(
        "syn_domain.contexts.github.slices.evaluate_webhook.EvaluateWebhookHandler"
    ) as mock_module:
        TriggerMatchResult = type("TriggerMatchResult", (), {"trigger_id": "t1"})
        TriggerDeferredResult = type("TriggerDeferredResult", (), {"trigger_id": "d1"})

        mock_module.TriggerMatchResult = TriggerMatchResult
        mock_module.TriggerDeferredResult = TriggerDeferredResult

        results = [TriggerMatchResult(), TriggerDeferredResult(), TriggerMatchResult()]
        # Need to patch the imports inside the function
        with (
            patch(
                "syn_domain.contexts.github.slices.evaluate_webhook.EvaluateWebhookHandler.TriggerMatchResult",
                TriggerMatchResult,
            ),
            patch(
                "syn_domain.contexts.github.slices.evaluate_webhook.EvaluateWebhookHandler.TriggerDeferredResult",
                TriggerDeferredResult,
            ),
        ):
            fired, deferred = _classify_trigger_results(results)

    assert len(fired) == 2
    assert len(deferred) == 1


# --- _evaluate_triggers ---


@pytest.mark.anyio
async def test_evaluate_triggers_exception_returns_empty() -> None:
    with (
        patch(
            "syn_api.routes.webhooks.handlers.get_trigger_store", side_effect=RuntimeError("boom")
        ),
        patch("syn_api.routes.webhooks.handlers.get_trigger_repo", return_value=MagicMock()),
        patch(
            "syn_domain.contexts.github.slices.evaluate_webhook.EvaluateWebhookHandler.EvaluateWebhookHandler",
            side_effect=RuntimeError("boom"),
        ),
    ):
        fired, deferred = await _evaluate_triggers("push", "", {}, "inst-1")

    assert fired == []
    assert deferred == []
