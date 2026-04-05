"""Tests for OTLP JSON parser.

Verifies that parse_otlp_metrics() and parse_otlp_logs() correctly extract
Claude Code OTel data into CollectedEvent instances.
"""

from __future__ import annotations

import pytest

from syn_collector.collector.otlp import parse_otlp_logs, parse_otlp_metrics
from syn_collector.events.types import EventType

# Sample OTLP metrics payload (Claude Code token usage)
SAMPLE_METRICS_PAYLOAD = {
    "resourceMetrics": [
        {
            "resource": {
                "attributes": [
                    {"key": "session.id", "value": {"stringValue": "sess-abc123"}},
                    {"key": "service.name", "value": {"stringValue": "claude-code"}},
                ]
            },
            "scopeMetrics": [
                {
                    "scope": {"name": "claude-code"},
                    "metrics": [
                        {
                            "name": "claude_code.token.usage",
                            "gauge": {
                                "dataPoints": [
                                    {
                                        "timeUnixNano": "1712250000000000000",
                                        "asInt": 1500,
                                        "attributes": [
                                            {
                                                "key": "type",
                                                "value": {"stringValue": "input"},
                                            },
                                        ],
                                    },
                                    {
                                        "timeUnixNano": "1712250000000000000",
                                        "asInt": 300,
                                        "attributes": [
                                            {
                                                "key": "type",
                                                "value": {"stringValue": "output"},
                                            },
                                        ],
                                    },
                                ],
                            },
                        },
                        {
                            "name": "claude_code.cost.usage",
                            "gauge": {
                                "dataPoints": [
                                    {
                                        "timeUnixNano": "1712250001000000000",
                                        "asDouble": 0.0045,
                                        "attributes": [],
                                    },
                                ],
                            },
                        },
                        {
                            "name": "process.cpu.time",
                            "sum": {
                                "dataPoints": [
                                    {"timeUnixNano": "1712250001000000000", "asDouble": 1.5},
                                ],
                            },
                        },
                    ],
                }
            ],
        }
    ]
}

# Sample OTLP logs payload
SAMPLE_LOGS_PAYLOAD = {
    "resourceLogs": [
        {
            "resource": {
                "attributes": [
                    {"key": "session.id", "value": {"stringValue": "sess-abc123"}},
                ]
            },
            "scopeLogs": [
                {
                    "logRecords": [
                        {
                            "timeUnixNano": "1712250002000000000",
                            "severityText": "INFO",
                            "body": {"stringValue": "Tool execution completed: Bash"},
                        },
                    ],
                }
            ],
        }
    ]
}


@pytest.mark.unit
class TestParseOtlpMetrics:
    """Tests for parse_otlp_metrics."""

    def test_extracts_token_usage(self) -> None:
        """Should extract claude_code.token.usage as TOKEN_USAGE events."""
        events = parse_otlp_metrics(SAMPLE_METRICS_PAYLOAD)

        token_events = [e for e in events if e.event_type == EventType.TOKEN_USAGE]
        assert len(token_events) == 2

        input_event = token_events[0]
        assert input_event.session_id == "sess-abc123"
        assert input_event.data["metric_name"] == "claude_code.token.usage"
        assert input_event.data["value"] == 1500
        assert input_event.data["type"] == "input"
        assert input_event.data["source"] == "otlp"

    def test_extracts_cost_usage(self) -> None:
        """Should extract claude_code.cost.usage as COST_RECORDED events."""
        events = parse_otlp_metrics(SAMPLE_METRICS_PAYLOAD)

        cost_events = [e for e in events if e.event_type == EventType.COST_RECORDED]
        assert len(cost_events) == 1
        assert cost_events[0].data["value"] == 0.0045

    def test_ignores_unknown_metrics(self) -> None:
        """Should ignore metrics not in KNOWN_METRICS."""
        events = parse_otlp_metrics(SAMPLE_METRICS_PAYLOAD)

        # process.cpu.time should be ignored
        metric_names = {e.data["metric_name"] for e in events}
        assert "process.cpu.time" not in metric_names

    def test_empty_payload(self) -> None:
        """Empty payload should return empty list."""
        events = parse_otlp_metrics({})
        assert events == []

    def test_empty_resource_metrics(self) -> None:
        """Payload with empty resourceMetrics should return empty list."""
        events = parse_otlp_metrics({"resourceMetrics": []})
        assert events == []

    def test_deterministic_event_ids(self) -> None:
        """Same payload should produce same event IDs."""
        events1 = parse_otlp_metrics(SAMPLE_METRICS_PAYLOAD)
        events2 = parse_otlp_metrics(SAMPLE_METRICS_PAYLOAD)

        ids1 = [e.event_id for e in events1]
        ids2 = [e.event_id for e in events2]
        assert ids1 == ids2

    def test_no_event_id_collisions_same_timestamp(self) -> None:
        """Datapoints with same timestamp but different index get unique IDs."""
        events = parse_otlp_metrics(SAMPLE_METRICS_PAYLOAD)

        # Two token usage events share timestamp 1712250000000000000
        token_events = [e for e in events if e.event_type == EventType.TOKEN_USAGE]
        assert len(token_events) == 2
        assert token_events[0].event_id != token_events[1].event_id

    def test_snake_case_keys(self) -> None:
        """Should handle snake_case OTLP keys (resource_metrics vs resourceMetrics)."""
        snake_payload = {
            "resource_metrics": [
                {
                    "resource": {"attributes": []},
                    "scope_metrics": [
                        {
                            "metrics": [
                                {
                                    "name": "claude_code.token.usage",
                                    "gauge": {
                                        "data_points": [
                                            {"time_unix_nano": 1712250000000000000, "as_int": 100},
                                        ],
                                    },
                                }
                            ]
                        }
                    ],
                }
            ]
        }
        events = parse_otlp_metrics(snake_payload)
        assert len(events) == 1
        assert events[0].data["value"] == 100


@pytest.mark.unit
class TestParseOtlpLogs:
    """Tests for parse_otlp_logs."""

    def test_extracts_log_records(self) -> None:
        """Should extract log records as OTLP_LOG events."""
        events = parse_otlp_logs(SAMPLE_LOGS_PAYLOAD)

        assert len(events) == 1
        event = events[0]
        assert event.event_type == EventType.OTLP_LOG
        assert event.session_id == "sess-abc123"
        assert event.data["body"] == "Tool execution completed: Bash"
        assert event.data["severity"] == "INFO"
        assert event.data["source"] == "otlp"

    def test_empty_payload(self) -> None:
        """Empty payload should return empty list."""
        events = parse_otlp_logs({})
        assert events == []

    def test_unique_ids_across_scope_logs(self) -> None:
        """Log records in different scopeLogs with same timestamp get unique event_ids."""
        payload = {
            "resourceLogs": [
                {
                    "resource": {
                        "attributes": [
                            {"key": "session.id", "value": {"stringValue": "sess-multi"}},
                        ]
                    },
                    "scopeLogs": [
                        {
                            "logRecords": [
                                {
                                    "timeUnixNano": "1712250000000000000",
                                    "severityText": "INFO",
                                    "body": {"stringValue": "log from scope 1"},
                                },
                            ],
                        },
                        {
                            "logRecords": [
                                {
                                    "timeUnixNano": "1712250000000000000",
                                    "severityText": "WARN",
                                    "body": {"stringValue": "log from scope 2"},
                                },
                            ],
                        },
                    ],
                }
            ]
        }
        events = parse_otlp_logs(payload)

        assert len(events) == 2
        assert events[0].event_id != events[1].event_id
