"""OTLP JSON receiver for workspace OTel metrics and logs.

Accepts OpenTelemetry JSON payloads from workspace containers and converts
them to CollectedEvent instances for the existing observability pipeline.

Claude Code exports OTel metrics/logs via OTLP when CLAUDE_CODE_ENABLE_TELEMETRY=1.
Key metrics: claude_code.token.usage, claude_code.cost.usage.

This module provides:
- parse_otlp_metrics(): Extract metrics from OTLP JSON → CollectedEvent list
- parse_otlp_logs(): Extract logs from OTLP JSON → CollectedEvent list
- OTLP route registration for /v1/metrics and /v1/logs

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


def _otlp_event_id(session_id: str, metric_name: str, timestamp: str) -> str:
    """Generate deterministic event ID for OTLP metric."""
    content = f"otlp:{session_id}:{metric_name}:{timestamp}"
    return hashlib.sha256(content.encode()).hexdigest()[:32]


def _extract_session_id(resource_attrs: list[dict[str, Any]]) -> str:
    """Extract session ID from OTel resource attributes."""
    for attr in resource_attrs:
        if attr.get("key") == "session.id":
            return str(attr.get("value", {}).get("stringValue", "unknown"))
    return "unknown"


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

    for resource_metrics in payload.get("resource_metrics", payload.get("resourceMetrics", [])):
        resource = resource_metrics.get("resource", {})
        resource_attrs = resource.get("attributes", [])
        session_id = _extract_session_id(resource_attrs)

        for scope_metrics in resource_metrics.get(
            "scope_metrics", resource_metrics.get("scopeMetrics", [])
        ):
            for metric in scope_metrics.get("metrics", []):
                metric_name = metric.get("name", "")
                if metric_name not in KNOWN_METRICS:
                    continue

                # Extract data points from gauge, sum, or histogram
                data_points = _extract_data_points(metric)

                for dp in data_points:
                    timestamp_ns = dp.get("time_unix_nano", dp.get("timeUnixNano", 0))
                    timestamp = datetime.fromtimestamp(
                        int(timestamp_ns) / 1e9, tz=UTC
                    ) if timestamp_ns else datetime.now(UTC)

                    value = dp.get("asDouble", dp.get("asInt", dp.get("as_double", dp.get("as_int", 0))))
                    attributes = {
                        attr.get("key", ""): _attr_value(attr.get("value", {}))
                        for attr in dp.get("attributes", [])
                    }

                    event_type = (
                        EventType.TOKEN_USAGE
                        if metric_name == METRIC_TOKEN_USAGE
                        else EventType.COST_RECORDED
                    )

                    event = CollectedEvent(
                        event_id=_otlp_event_id(session_id, metric_name, str(timestamp_ns)),
                        event_type=event_type,
                        session_id=session_id,
                        timestamp=timestamp,
                        data={
                            "source": "otlp",
                            "metric_name": metric_name,
                            "value": value,
                            **attributes,
                        },
                    )
                    events.append(event)

    return events


def parse_otlp_logs(payload: dict[str, Any]) -> list[CollectedEvent]:
    """Parse OTLP JSON logs payload into CollectedEvent instances.

    Extracts log records and converts them to generic session events.

    Args:
        payload: OTLP JSON logs payload (ExportLogsServiceRequest).

    Returns:
        List of CollectedEvent instances.
    """
    events: list[CollectedEvent] = []

    for resource_logs in payload.get("resource_logs", payload.get("resourceLogs", [])):
        resource = resource_logs.get("resource", {})
        resource_attrs = resource.get("attributes", [])
        session_id = _extract_session_id(resource_attrs)

        for scope_logs in resource_logs.get("scope_logs", resource_logs.get("scopeLogs", [])):
            for log_record in scope_logs.get("log_records", scope_logs.get("logRecords", [])):
                timestamp_ns = log_record.get(
                    "time_unix_nano", log_record.get("timeUnixNano", 0)
                )
                timestamp = datetime.fromtimestamp(
                    int(timestamp_ns) / 1e9, tz=UTC
                ) if timestamp_ns else datetime.now(UTC)

                body = log_record.get("body", {}).get("stringValue", "")
                severity = log_record.get(
                    "severity_text", log_record.get("severityText", "INFO")
                )

                event_id = _otlp_event_id(session_id, "log", str(timestamp_ns))

                event = CollectedEvent(
                    event_id=event_id,
                    event_type=EventType.SESSION_STARTED,  # Generic — refined by downstream
                    session_id=session_id,
                    timestamp=timestamp,
                    data={
                        "source": "otlp",
                        "severity": severity,
                        "body": body[:2000],  # Truncate oversized log bodies
                    },
                )
                events.append(event)

    return events


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
