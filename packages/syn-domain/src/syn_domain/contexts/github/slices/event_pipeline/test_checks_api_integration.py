"""Integration test: Checks API → synthesize → pipeline → self-healing trigger fires.

Exercises the full poll-based self-healing flow (#602):
  raw Checks API JSON → synthesize_check_run_event → EventPipeline.ingest
  → SELF_HEALING_PRESET conditions evaluate → trigger fires with correct inputs

This is *not* a unit test — it wires together the synthesizer, pipeline, dedup,
condition evaluator, and trigger store to validate end-to-end correctness.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from syn_domain.contexts.github._shared.trigger_presets import SELF_HEALING_PRESET
from syn_domain.contexts.github._shared.trigger_query_store import InMemoryTriggerQueryStore
from syn_domain.contexts.github.slices.evaluate_webhook.EvaluateWebhookHandler import (
    EvaluateWebhookHandler,
)
from syn_domain.contexts.github.slices.event_pipeline.check_run_synthesizer import (
    synthesize_check_run_event,
)
from syn_domain.contexts.github.slices.event_pipeline.normalized_event import EventSource
from syn_domain.contexts.github.slices.event_pipeline.pending_sha_port import PendingSHA
from syn_domain.contexts.github.slices.event_pipeline.pipeline import EventPipeline

# ---------------------------------------------------------------------------
# Fixtures — realistic Checks API response matching production shape
# ---------------------------------------------------------------------------

# This is the shape returned by GET /repos/{owner}/{repo}/commits/{ref}/check-runs
# Captured from GitHub's Checks API documentation + real responses.
REALISTIC_CHECK_RUNS_RESPONSE: dict[str, Any] = {
    "total_count": 3,
    "check_runs": [
        {
            "id": 28930145617,
            "name": "lint",
            "status": "completed",
            "conclusion": "success",
            "started_at": "2026-04-05T14:22:10Z",
            "completed_at": "2026-04-05T14:23:45Z",
            "html_url": "https://github.com/acme/widget/runs/28930145617",
            "output": {
                "title": "Lint passed",
                "summary": "All checks passed",
                "text": None,
                "annotations_count": 0,
            },
            "app": {"slug": "github-actions"},
        },
        {
            "id": 28930145618,
            "name": "test",
            "status": "completed",
            "conclusion": "failure",
            "started_at": "2026-04-05T14:22:10Z",
            "completed_at": "2026-04-05T14:25:33Z",
            "html_url": "https://github.com/acme/widget/runs/28930145618",
            "output": {
                "title": "3 tests failed",
                "summary": "test_auth.py::test_login_redirect FAILED\ntest_auth.py::test_token_refresh FAILED\ntest_api.py::test_rate_limit FAILED",
                "text": None,
                "annotations_count": 3,
            },
            "app": {"slug": "github-actions"},
        },
        {
            "id": 28930145619,
            "name": "typecheck",
            "status": "in_progress",
            "conclusion": None,
            "started_at": "2026-04-05T14:22:10Z",
            "completed_at": None,
            "html_url": "https://github.com/acme/widget/runs/28930145619",
            "output": {
                "title": None,
                "summary": None,
                "text": None,
                "annotations_count": 0,
            },
            "app": {"slug": "github-actions"},
        },
    ],
}


def _make_pending() -> PendingSHA:
    return PendingSHA(
        repository="acme/widget",
        sha="d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3",
        pr_number=137,
        branch="feat/oauth-refresh",
        installation_id="98765",
        registered_at=datetime(2026, 4, 5, 14, 20, 0, tzinfo=UTC),
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _InMemoryDedup:
    def __init__(self) -> None:
        self._seen: set[str] = set()

    async def is_duplicate(self, dedup_key: str) -> bool:
        if dedup_key in self._seen:
            return True
        self._seen.add(dedup_key)
        return False

    async def mark_seen(self, dedup_key: str) -> None:
        self._seen.add(dedup_key)


class _NullRepository:
    async def get_by_id(self, aggregate_id: str) -> None:
        return None

    async def save(self, aggregate: object) -> None:
        pass


def _make_config() -> Any:  # noqa: ANN401
    from syn_domain.contexts.github.domain.aggregate_trigger.TriggerConfig import TriggerConfig

    return TriggerConfig()


async def _register_self_healing_trigger(
    store: InMemoryTriggerQueryStore,
    trigger_id: str = "tr-self-heal",
    repository: str = "acme/widget",
) -> None:
    """Register a trigger using the actual SELF_HEALING_PRESET conditions and mappings."""
    await store.index_trigger(
        trigger_id=trigger_id,
        name="self-healing-ci",
        event=SELF_HEALING_PRESET["event"],
        repository=repository,
        workflow_id="ci-fix-v1",
        conditions=list(SELF_HEALING_PRESET["conditions"]),
        input_mapping=dict(SELF_HEALING_PRESET["input_mapping"]),
        config=_make_config(),
        installation_id="98765",
        created_by="test",
        status="active",
    )


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestChecksApiSelfHealingFlow:
    """End-to-end: Checks API response → synthesize → pipeline → trigger fires."""

    @pytest.mark.asyncio
    async def test_failed_check_run_triggers_self_healing(self) -> None:
        """A failed check run from the Checks API triggers the self-healing workflow."""
        pending = _make_pending()
        store = InMemoryTriggerQueryStore()
        await _register_self_healing_trigger(store)

        pipeline = EventPipeline(
            dedup=_InMemoryDedup(),
            evaluator=EvaluateWebhookHandler(store=store, repository=_NullRepository()),
        )

        # Simulate what CheckRunPoller does: iterate check runs from the API response
        fired_triggers: list[str] = []
        for raw_check_run in REALISTIC_CHECK_RUNS_RESPONSE["check_runs"]:
            event = synthesize_check_run_event(raw_check_run, pending)
            if event is not None:
                result = await pipeline.ingest(event)
                if result.status == "processed":
                    fired_triggers.extend(result.triggers_fired)

        # Only the failed "test" check run should have fired
        assert fired_triggers == ["tr-self-heal"]

    @pytest.mark.asyncio
    async def test_synthesized_event_has_correct_source(self) -> None:
        """Events from Checks API polling are tagged with CHECKS_API source."""
        pending = _make_pending()
        failed_run = REALISTIC_CHECK_RUNS_RESPONSE["check_runs"][1]  # "test" — failure

        event = synthesize_check_run_event(failed_run, pending)
        assert event is not None
        assert event.source == EventSource.CHECKS_API

    @pytest.mark.asyncio
    async def test_successful_check_run_does_not_synthesize(self) -> None:
        """Successful check runs produce no event — only failures trigger."""
        pending = _make_pending()
        success_run = REALISTIC_CHECK_RUNS_RESPONSE["check_runs"][0]  # "lint" — success

        event = synthesize_check_run_event(success_run, pending)
        assert event is None

    @pytest.mark.asyncio
    async def test_in_progress_check_run_does_not_synthesize(self) -> None:
        """In-progress check runs produce no event — wait for completion."""
        pending = _make_pending()
        in_progress_run = REALISTIC_CHECK_RUNS_RESPONSE["check_runs"][2]  # "typecheck"

        event = synthesize_check_run_event(in_progress_run, pending)
        assert event is None

    @pytest.mark.asyncio
    async def test_trigger_inputs_extract_correctly(self) -> None:
        """All 7 SELF_HEALING_PRESET input mappings extract the correct values."""
        from syn_domain.contexts.github.slices.evaluate_webhook.condition_evaluator import (
            extract_inputs,
        )

        pending = _make_pending()
        failed_run = REALISTIC_CHECK_RUNS_RESPONSE["check_runs"][1]

        event = synthesize_check_run_event(failed_run, pending)
        assert event is not None

        inputs = extract_inputs(event.payload, dict(SELF_HEALING_PRESET["input_mapping"]))

        assert inputs["repository"] == "acme/widget"
        assert inputs["pr_number"] == 137
        assert inputs["branch"] == "feat/oauth-refresh"
        assert inputs["check_name"] == "test"
        assert inputs["check_output_title"] == "3 tests failed"
        assert inputs["check_output_summary"].startswith("test_auth.py")
        assert "runs/28930145618" in inputs["check_html_url"]

    @pytest.mark.asyncio
    async def test_dedup_prevents_double_fire(self) -> None:
        """Same check run ingested twice → only fires once."""
        pending = _make_pending()
        store = InMemoryTriggerQueryStore()
        await _register_self_healing_trigger(store)

        dedup = _InMemoryDedup()
        pipeline = EventPipeline(
            dedup=dedup,
            evaluator=EvaluateWebhookHandler(store=store, repository=_NullRepository()),
        )

        failed_run = REALISTIC_CHECK_RUNS_RESPONSE["check_runs"][1]
        event = synthesize_check_run_event(failed_run, pending)
        assert event is not None

        first = await pipeline.ingest(event)
        second = await pipeline.ingest(event)

        assert first.status == "processed"
        assert first.triggers_fired == ["tr-self-heal"]
        assert second.status == "deduplicated"

    @pytest.mark.asyncio
    async def test_webhook_and_poll_dedup_to_same_key(self) -> None:
        """A webhook check_run.completed and a synthesized one share the same dedup key."""
        from syn_domain.contexts.github.slices.event_pipeline.dedup_keys import compute_dedup_key

        pending = _make_pending()
        failed_run = REALISTIC_CHECK_RUNS_RESPONSE["check_runs"][1]

        # Synthesized event from Checks API
        synth_event = synthesize_check_run_event(failed_run, pending)
        assert synth_event is not None

        # Simulate a webhook payload for the same check run
        webhook_payload = synth_event.payload  # Same structure
        webhook_key = compute_dedup_key("check_run", "completed", webhook_payload)

        assert synth_event.dedup_key == webhook_key

    @pytest.mark.asyncio
    async def test_no_trigger_registered_no_fire(self) -> None:
        """When no self-healing trigger is registered, the event is processed but nothing fires."""
        pending = _make_pending()
        store = InMemoryTriggerQueryStore()
        # Deliberately NOT registering any trigger

        pipeline = EventPipeline(
            dedup=_InMemoryDedup(),
            evaluator=EvaluateWebhookHandler(store=store, repository=_NullRepository()),
        )

        failed_run = REALISTIC_CHECK_RUNS_RESPONSE["check_runs"][1]
        event = synthesize_check_run_event(failed_run, pending)
        assert event is not None

        result = await pipeline.ingest(event)
        assert result.status == "processed"
        assert result.triggers_fired == []
