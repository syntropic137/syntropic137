"""OTLP JSON receiver for workspace OTel metrics and logs.

Accepts OpenTelemetry JSON payloads from workspace containers and converts
them to CollectedEvent instances for the existing observability pipeline.

Claude Code exports OTel metrics/logs via OTLP when CLAUDE_CODE_ENABLE_TELEMETRY=1.
Key metrics: claude_code.token.usage, claude_code.cost.usage.

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

from syn_collector.events.types import CollectedEvent, EventType

logger = logging.getLogger(__name__)

# Metric names we extract from OTLP payloads
METRIC_TOKEN_USAGE = "claude_code.token.usage"
METRIC_COST_USAGE = "claude_code.cost.usage"
KNOWN_METRICS: frozenset[str] = frozenset({METRIC_TOKEN_USAGE, METRIC_COST_USAGE})

_METRIC_TO_EVENT_TYPE: dict[str, EventType] = {
    METRIC_TOKEN_USAGE: EventType.TOKEN_USAGE,
    METRIC_COST_USAGE: EventType.COST_RECORDED,
}


def _otlp_event_id(session_id: str, metric_name: str, timestamp: str, index: int = 0) -> str:
    """Generate deterministic event ID for OTLP metric.

    Includes a datapoint index to avoid collisions when multiple datapoints
    share the same session, metric name, and timestamp (e.g. token usage
    broken down by input/output/cache).
    """
    content = f"otlp:{session_id}:{metric_name}:{timestamp}:{index}"
    return hashlib.sha256(content.encode()).hexdigest()[:32]


def _extract_session_id(resource_attrs: list[dict[str, Any]]) -> str:
    """Extract session ID from OTel resource attributes."""
    for attr in resource_attrs:
        if attr.get("key") == "session.id":
            return str(attr.get("value", {}).get("stringValue", "unknown"))
    return "unknown"


def _timestamp_from_nanos(timestamp_ns: int | str) -> datetime:
    """Convert nanosecond timestamp to datetime."""
    ns = int(timestamp_ns)
    if ns:
        return datetime.fromtimestamp(ns / 1e9, tz=UTC)
    return datetime.now(UTC)


def _extract_data_points(metric: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract data points from any metric type (gauge, sum, histogram)."""
    for key in ("gauge", "sum", "histogram"):
        section = metric.get(key)
        if section:
            return section.get("data_points", section.get("dataPoints", []))
    return []


def _attr_value(value_obj: dict[str, Any]) -> str | int | float | bool:
    """Extract a scalar value from an OTel attribute value wrapper."""
    for key in ("stringValue", "intValue", "doubleValue", "boolValue"):
        if key in value_obj:
            return value_obj[key]  # type: ignore[no-any-return]
    return ""


def _datapoint_to_event(
    dp: dict[str, Any],
    index: int,
    session_id: str,
    metric_name: str,
) -> CollectedEvent:
    """Convert a single OTLP data point into a CollectedEvent."""
    timestamp_ns = dp.get("time_unix_nano", dp.get("timeUnixNano", 0))
    timestamp = _timestamp_from_nanos(timestamp_ns)

    value = dp.get("asDouble", dp.get("asInt", dp.get("as_double", dp.get("as_int", 0))))
    attributes = {
        attr.get("key", ""): _attr_value(attr.get("value", {})) for attr in dp.get("attributes", [])
    }

    return CollectedEvent(
        event_id=_otlp_event_id(session_id, metric_name, str(timestamp_ns), index),
        event_type=_METRIC_TO_EVENT_TYPE[metric_name],
        session_id=session_id,
        timestamp=timestamp,
        data={
            "source": "otlp",
            "metric_name": metric_name,
            "value": value,
            **attributes,
        },
    )


def _get(d: dict[str, Any], snake: str, camel: str) -> Any:
    """Get a value by snake_case key, falling back to camelCase."""
    return d.get(snake, d.get(camel, []))


def _collect_known_datapoints(
    scope_metrics_list: list[dict[str, Any]],
    session_id: str,
    start_index: int,
) -> list[CollectedEvent]:
    """Extract events from scope_metrics for known metric names."""
    events: list[CollectedEvent] = []
    idx = start_index
    for scope_metrics in scope_metrics_list:
        for metric in scope_metrics.get("metrics", []):
            metric_name = metric.get("name", "")
            if metric_name not in KNOWN_METRICS:
                continue
            for dp in _extract_data_points(metric):
                events.append(_datapoint_to_event(dp, idx, session_id, metric_name))
                idx += 1
    return events


def parse_otlp_metrics(payload: dict[str, Any]) -> list[CollectedEvent]:
    """Parse OTLP JSON metrics payload into CollectedEvent instances.

    Extracts known Claude Code metrics (token usage, cost) and converts
    them to CollectedEvents that flow through the existing pipeline.

    Args:
        payload: OTLP JSON metrics payload (ExportMetricsServiceRequest).

    Returns:
        List of CollectedEvent instances for known metrics.
    """
    events: list[CollectedEvent] = []
    dp_index = 0

    for resource_metrics in _get(payload, "resource_metrics", "resourceMetrics"):
        resource = resource_metrics.get("resource", {})
        session_id = _extract_session_id(resource.get("attributes", []))
        scope_list = _get(resource_metrics, "scope_metrics", "scopeMetrics")
        batch = _collect_known_datapoints(scope_list, session_id, dp_index)
        dp_index += len(batch)
        events.extend(batch)

    return events


def parse_otlp_logs(payload: dict[str, Any]) -> list[CollectedEvent]:
    """Parse OTLP JSON logs payload into CollectedEvent instances.

    Extracts log records and converts them to OTLP_LOG events.

    Args:
        payload: OTLP JSON logs payload (ExportLogsServiceRequest).

    Returns:
        List of CollectedEvent instances.
    """
    events: list[CollectedEvent] = []

    for resource_logs in _get(payload, "resource_logs", "resourceLogs"):
        resource = resource_logs.get("resource", {})
        session_id = _extract_session_id(resource.get("attributes", []))

        for scope_logs in _get(resource_logs, "scope_logs", "scopeLogs"):
            for i, log_record in enumerate(_get(scope_logs, "log_records", "logRecords")):
                timestamp_ns = log_record.get("time_unix_nano", log_record.get("timeUnixNano", 0))
                timestamp = _timestamp_from_nanos(timestamp_ns)

                body = log_record.get("body", {}).get("stringValue", "")
                severity = log_record.get("severity_text", log_record.get("severityText", "INFO"))

                events.append(
                    CollectedEvent(
                        event_id=_otlp_event_id(session_id, "log", str(timestamp_ns), i),
                        event_type=EventType.OTLP_LOG,
                        session_id=session_id,
                        timestamp=timestamp,
                        data={
                            "source": "otlp",
                            "severity": severity,
                            "body": body[:2000],
                        },
                    )
                )

    return events
