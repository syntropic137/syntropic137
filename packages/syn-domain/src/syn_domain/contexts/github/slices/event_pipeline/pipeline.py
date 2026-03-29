"""EventPipeline — unified ingestion with dedup for webhook and polling sources."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from syn_domain.contexts.github.slices.evaluate_webhook.EvaluateWebhookHandler import (
    EvaluateWebhookHandler,
    TriggerDeferredResult,
    TriggerMatchResult,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

    from syn_domain.contexts.github._shared.trigger_query_store import TriggerQueryStore
    from syn_domain.contexts.github.slices.evaluate_webhook.debouncer import TriggerDebouncer
    from syn_domain.contexts.github.slices.event_pipeline.dedup_port import DedupPort
    from syn_domain.contexts.github.slices.event_pipeline.normalized_event import NormalizedEvent

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PipelineResult:
    """Result of processing a normalized event through the pipeline."""

    status: str
    """``"deduplicated"`` | ``"processed"``"""

    event_type: str
    triggers_fired: list[str] = field(default_factory=list)
    deferred: list[str] = field(default_factory=list)


class EventPipeline:
    """Unified ingestion pipeline for GitHub events.

    Both webhook endpoint and poller feed ``NormalizedEvent`` instances into
    ``ingest()``, which deduplicates and routes to the trigger evaluation handler.

    ::

        Webhook endpoint ──┐
                           ├──> ingest(event) ──> dedup ──> EvaluateWebhookHandler
        Poller loop ───────┘
    """

    def __init__(
        self,
        dedup: DedupPort,
        trigger_store: TriggerQueryStore,
        trigger_repo: object,
        debouncer: TriggerDebouncer | None = None,
        on_fire: Callable[[Any, dict[str, Any]], Coroutine[Any, Any, None]] | None = None,
    ) -> None:
        self._dedup = dedup
        self._handler = EvaluateWebhookHandler(
            store=trigger_store,
            repository=trigger_repo,
            debouncer=debouncer,
            on_fire=on_fire,
        )

    async def ingest(self, event: NormalizedEvent) -> PipelineResult:
        """Process a normalized event through dedup and trigger evaluation.

        Dedup is fail-open: if the dedup backend is unavailable, the event
        is processed anyway. Safety guards in ``EvaluateWebhookHandler``
        (fire counts, cooldowns) provide second-layer protection.
        """
        # 1. Dedup check
        try:
            if await self._dedup.is_duplicate(event.dedup_key):
                logger.debug(
                    "Deduplicated event %s from %s",
                    event.dedup_key,
                    event.source.value,
                )
                return PipelineResult(status="deduplicated", event_type=event.event_type)
        except Exception:
            logger.warning(
                "Dedup check failed for %s — processing anyway (fail-open)",
                event.dedup_key,
                exc_info=True,
            )

        # 2. Build compound event and inject delivery_id for backward compat
        compound_event = f"{event.event_type}.{event.action}" if event.action else event.event_type
        payload = {**event.payload, "_delivery_id": event.delivery_id}

        # 3. Evaluate triggers
        results = await self._handler.evaluate(
            event=compound_event,
            repository=event.repository,
            installation_id=event.installation_id,
            payload=payload,
        )

        fired, deferred = _classify_results(results)
        return PipelineResult(
            status="processed",
            event_type=event.event_type,
            triggers_fired=fired,
            deferred=deferred,
        )


def _classify_results(
    results: list[TriggerMatchResult | TriggerDeferredResult],
) -> tuple[list[str], list[str]]:
    """Separate trigger evaluation results into (fired, deferred) ID lists."""
    fired: list[str] = []
    deferred: list[str] = []
    for r in results:
        if isinstance(r, TriggerMatchResult):
            fired.append(r.trigger_id)
        elif isinstance(r, TriggerDeferredResult):
            deferred.append(r.trigger_id)
    return fired, deferred
