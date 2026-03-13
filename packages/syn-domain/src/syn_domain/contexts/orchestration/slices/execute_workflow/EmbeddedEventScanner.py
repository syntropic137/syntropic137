"""EmbeddedEventScanner — scans tool output for embedded hook events (ADR-043).

Git hooks running inside tool execution emit JSONL to stdout/stderr.
This scanner finds those events, validates, enriches, and records
via ObservabilityCollector.

Extracted from EventStreamProcessor._handle_tool_result() (ISS-196).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

# Any: dict[str, Any] used for JSON data from parse_jsonl_line() (system boundary — external CLI JSONL)
from agentic_events import enrich_event, parse_jsonl_line

from syn_shared.events import VALID_EVENT_TYPES

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration.slices.execute_workflow.ObservabilityCollector import (
        ObservabilityCollector,
    )

logger = logging.getLogger(__name__)


class EmbeddedEventScanner:
    """Scans tool output for embedded hook events (ADR-043).

    Git hooks running inside tool execution emit JSONL to stdout/stderr.
    This scanner finds those events, validates, enriches, and records
    via ObservabilityCollector.
    """

    def __init__(
        self,
        collector: ObservabilityCollector,
        execution_id: str,
        phase_id: str,
    ) -> None:
        self._collector = collector
        self._execution_id = execution_id
        self._phase_id = phase_id

    async def scan_and_record(self, tool_content: str, tool_name: str) -> None:
        """Scan tool output for embedded JSONL and record valid events."""
        for tl in tool_content.splitlines():
            tl = tl.strip()
            if not tl:
                continue
            embedded = parse_jsonl_line(tl)
            if not embedded:
                continue
            et = embedded.get("event_type")
            if et not in VALID_EVENT_TYPES:
                logger.debug("Unknown event_type in tool output: %s", et)
                continue
            enriched = enrich_event(
                embedded,
                execution_id=self._execution_id,
                phase_id=self._phase_id,
            )
            await self._collector.record_embedded_event(et, enriched)
            logger.info(
                "Git hook event from tool output: %s (tool=%s)",
                et,
                tool_name,
            )
