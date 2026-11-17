"""OTLP JSON receiver for workspace OTel metrics and logs.

Accepts OpenTelemetry JSON payloads from workspace containers and converts
them to CollectedEvent instances for the existing observability pipeline.

Claude Code exports OTel metrics/logs via OTLP when CLAUDE_CODE_ENABLE_TELEMETRY=1.

Metrics exported by Claude Code:
- claude_code.token.usage    → TOKEN_USAGE (input/output/cache token counts)
- claude_code.cost.usage     → COST_RECORDED (cumulative cost in USD)
- claude_code.session.count  → SESSION_STARTED (session counter)
- claude_code.commit.count   → GIT_COMMIT (commit counter)

OTel log events exported by Claude Code:
- claude_code.api_request    → API_REQUEST (per-call cost, model, cache, duration)
- claude_code.api_error      → API_ERROR (error, status_code, retry count)
- claude_code.tool_result    → TOOL_EXECUTION_COMPLETED (tool name, duration, success)
- claude_code.user_prompt    → USER_PROMPT_SUBMITTED (prompt length)
- (unknown)                  → OTLP_LOG (raw log body, for forward-compat)

This module provides:
- parse_otlp_metrics(): Extract metrics from OTLP JSON -> CollectedEvent list
- parse_otlp_logs(): Extract logs from OTLP JSON -> CollectedEvent list

See ADR-056: Workspace Tooling Architecture (two-channel observability).
"""

from __future__ import annotations

import hashlib
import logging
from datetime import UTC, datetime
from typing import Any

from syn_collector.collector.otlp_envelope import (
    OtlpLogRecord,
    OtlpLogsRequest,
    OtlpMetricsRequest,
    OtlpNumberDataPoint,
    OtlpScopeMetrics,
    attributes_to_dict,
)
from syn_collector.events.types import CollectedEvent, EventType

logger = logging.getLogger(__name__)

# Metric names we extract from OTLP payloads
METRIC_TOKEN_USAGE = "claude_code.token.usage"
METRIC_COST_USAGE = "claude_code.cost.usage"
METRIC_SESSION_COUNT = "claude_code.session.count"
METRIC_COMMIT_COUNT = "claude_code.commit.count"

KNOWN_METRICS: frozenset[str] = frozenset(
    {
        METRIC_TOKEN_USAGE,
        METRIC_COST_USAGE,
        METRIC_SESSION_COUNT,
        METRIC_COMMIT_COUNT,
    }
)

_METRIC_TO_EVENT_TYPE: dict[str, EventType] = {
    METRIC_TOKEN_USAGE: EventType.TOKEN_USAGE,
    METRIC_COST_USAGE: EventType.COST_RECORDED,
    METRIC_SESSION_COUNT: EventType.OTLP_SESSION_COUNT,
    METRIC_COMMIT_COUNT: EventType.OTLP_COMMIT_COUNT,
}

# OTel log event names → EventType
_LOG_EVENT_TO_EVENT_TYPE: dict[str, EventType] = {
    "claude_code.api_request": EventType.API_REQUEST,
    "claude_code.api_error": EventType.API_ERROR,
    "claude_code.tool_result": EventType.TOOL_EXECUTION_COMPLETED,
    "claude_code.user_prompt": EventType.USER_PROMPT_SUBMITTED,
}


def _otlp_event_id(session_id: str, metric_name: str, timestamp: str, index: int = 0) -> str:
    """Generate deterministic event ID for OTLP metric.

    Includes a datapoint index to avoid collisions when multiple datapoints
    share the same session, metric name, and timestamp (e.g. token usage
    broken down by input/output/cache).
    """
    content = f"otlp:{session_id}:{metric_name}:{timestamp}:{index}"
    return hashlib.sha256(content.encode()).hexdigest()[:32]


def _timestamp_from_nanos(timestamp_ns: int | str) -> datetime:
    """Convert nanosecond timestamp to datetime."""
    ns = int(timestamp_ns)
    if ns:
        return datetime.fromtimestamp(ns / 1e9, tz=UTC)
    return datetime.now(UTC)


def _datapoint_to_event(
    dp: OtlpNumberDataPoint,
    index: int,
    session_id: str,
    metric_name: str,
) -> CollectedEvent:
    """Convert a single OTLP data point into a CollectedEvent."""
    timestamp_ns = dp.time_unix_nano
    timestamp = _timestamp_from_nanos(timestamp_ns)

    return CollectedEvent(
        event_id=_otlp_event_id(session_id, metric_name, str(timestamp_ns), index),
        event_type=_METRIC_TO_EVENT_TYPE[metric_name],
        session_id=session_id,
        timestamp=timestamp,
        data={
            "source": "otlp",
            "metric_name": metric_name,
            "value": dp.value,
            **attributes_to_dict(dp.attributes),
        },
    )


def _collect_known_datapoints(
    scope_metrics_list: list[OtlpScopeMetrics],
    session_id: str,
    start_index: int,
) -> list[CollectedEvent]:
    """Extract events from scope_metrics for known metric names."""
    events: list[CollectedEvent] = []
    idx = start_index
    for scope_metrics in scope_metrics_list:
        for metric in scope_metrics.metrics:
            metric_name = metric.name
            if metric_name not in KNOWN_METRICS:
                continue
            for dp in metric.data_points():
                events.append(_datapoint_to_event(dp, idx, session_id, metric_name))
                idx += 1
    return events


def parse_otlp_metrics(payload: dict[str, Any]) -> list[CollectedEvent]:
    """Parse OTLP JSON metrics payload into CollectedEvent instances.

    Extracts known Claude Code metrics (token usage, cost) and converts
    them to CollectedEvents that flow through the existing pipeline.

    Args:
        payload: OTLP JSON metrics payload (ExportMetricsServiceRequest),
            raw from the request body; parsed into the typed envelope here.

    Returns:
        List of CollectedEvent instances for known metrics.
    """
    events: list[CollectedEvent] = []
    dp_index = 0

    request = OtlpMetricsRequest.model_validate(payload)
    for resource_metrics in request.resource_metrics:
        session_id = resource_metrics.resource.session_id()
        batch = _collect_known_datapoints(resource_metrics.scope_metrics, session_id, dp_index)
        dp_index += len(batch)
        events.extend(batch)

    return events


def _parse_log_record(
    log_record: OtlpLogRecord,
    index: int,
    session_id: str,
) -> CollectedEvent:
    """Convert a single OTel log record into a CollectedEvent.

    Structured log events (e.g. claude_code.api_request) are mapped to
    specific EventTypes. Unknown events fall back to OTLP_LOG.
    """
    timestamp_ns = log_record.time_unix_nano
    timestamp = _timestamp_from_nanos(timestamp_ns)
    severity = log_record.severity_text

    # Extract event name from log record attributes (Claude Code sets event.name)
    log_attrs = attributes_to_dict(log_record.attributes)
    event_name = str(log_attrs.get("event.name", ""))
    event_type = _LOG_EVENT_TO_EVENT_TYPE.get(event_name, EventType.OTLP_LOG)

    # Build data payload — include all attributes for known events.
    # For unknown events, preserve the body plus enough structured context
    # for forward-compatible debugging without emitting an unbounded payload.
    if event_type != EventType.OTLP_LOG:
        data: dict[str, Any] = {"source": "otlp", **log_attrs}
    else:
        body = log_record.body.string_value or ""
        bounded_attrs: dict[str, str | int | float | bool] = {}
        for k, v in list(log_attrs.items())[:50]:
            bounded_attrs[k] = v[:500] if isinstance(v, str) else v
        data = {
            "source": "otlp",
            "severity": severity,
            "body": body[:2000],
            "event_name": event_name,
            "log_attrs": bounded_attrs,
        }

    return CollectedEvent(
        event_id=_otlp_event_id(session_id, event_name or "log", str(timestamp_ns), index),
        event_type=event_type,
        session_id=session_id,
        timestamp=timestamp,
        data=data,
    )


def parse_otlp_logs(payload: dict[str, Any]) -> list[CollectedEvent]:
    """Parse OTLP JSON logs payload into CollectedEvent instances.

    Handles structured Claude Code log events (api_request, api_error,
    tool_result, user_prompt) and falls back to OTLP_LOG for unknowns.

    Args:
        payload: OTLP JSON logs payload (ExportLogsServiceRequest),
            raw from the request body; parsed into the typed envelope here.

    Returns:
        List of CollectedEvent instances.
    """
    events: list[CollectedEvent] = []
    log_index = 0

    request = OtlpLogsRequest.model_validate(payload)
    for resource_logs in request.resource_logs:
        session_id = resource_logs.resource.session_id()

        for scope_logs in resource_logs.scope_logs:
            for log_record in scope_logs.log_records:
                events.append(_parse_log_record(log_record, log_index, session_id))
                log_index += 1

    return events
