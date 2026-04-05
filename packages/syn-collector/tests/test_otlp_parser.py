"""Tests for OTLP JSON parser.

Verifies that parse_otlp_metrics() and parse_otlp_logs() correctly extract
Claude Code OTel data into CollectedEvent instances.
"""

from __future__ import annotations

import pytest

from syn_collector.collector.otlp import parse_otlp_logs, parse_otlp_metrics
from syn_collector.events.types import EventType


def _log_payload(event_name: str, attrs: dict[str, str | int | float]) -> dict:
    """Build a minimal OTLP logs payload with a structured log event."""
    attributes = [
        {"key": k, "value": {"stringValue": str(v)} if isinstance(v, str) else {"doubleValue": v}}
        for k, v in attrs.items()
    ]
    attributes.insert(0, {"key": "event.name", "value": {"stringValue": event_name}})
    return {
        "resourceLogs": [
            {
                "resource": {
                    "attributes": [
                        {"key": "session.id", "value": {"stringValue": "sess-xyz789"}},
                    ]
                },
                "scopeLogs": [
                    {
                        "logRecords": [
                            {
                                "timeUnixNano": "1712250005000000000",
                                "severityText": "INFO",
                                "attributes": attributes,
                            }
                        ]
                    }
                ],
            }
        ]
    }


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


@pytest.mark.unit
class TestStructuredLogEvents:
    """Tests for structured Claude Code OTel log event parsing."""

    def test_api_request_event(self) -> None:
        """claude_code.api_request log → API_REQUEST event with cost/model fields."""
        payload = _log_payload(
            "claude_code.api_request",
            {
                "model": "claude-opus-4-6",
                "cost_usd": 0.0312,
                "duration_ms": 1842.0,
                "input_tokens": 2500.0,
                "output_tokens": 800.0,
                "cache_read_tokens": 1200.0,
                "cache_creation_tokens": 0.0,
                "speed": "normal",
            },
        )
        events = parse_otlp_logs(payload)

        assert len(events) == 1
        event = events[0]
        assert event.event_type == EventType.API_REQUEST
        assert event.session_id == "sess-xyz789"
        assert event.data["event.name"] == "claude_code.api_request"
        assert event.data["model"] == "claude-opus-4-6"
        assert event.data["source"] == "otlp"

    def test_api_error_event(self) -> None:
        """claude_code.api_error log → API_ERROR event."""
        payload = _log_payload(
            "claude_code.api_error",
            {
                "model": "claude-opus-4-6",
                "error": "overloaded_error",
                "status_code": 529.0,
                "duration_ms": 312.0,
                "attempt": 2.0,
            },
        )
        events = parse_otlp_logs(payload)

        assert len(events) == 1
        assert events[0].event_type == EventType.API_ERROR
        assert events[0].data["error"] == "overloaded_error"

    def test_tool_result_event(self) -> None:
        """claude_code.tool_result log → TOOL_EXECUTION_COMPLETED event."""
        payload = _log_payload(
            "claude_code.tool_result",
            {
                "tool_name": "Bash",
                "success": "true",
                "duration_ms": 234.0,
            },
        )
        events = parse_otlp_logs(payload)

        assert len(events) == 1
        assert events[0].event_type == EventType.TOOL_EXECUTION_COMPLETED
        assert events[0].data["tool_name"] == "Bash"

    def test_user_prompt_event(self) -> None:
        """claude_code.user_prompt log → USER_PROMPT_SUBMITTED event."""
        payload = _log_payload("claude_code.user_prompt", {"prompt_length": 142.0})
        events = parse_otlp_logs(payload)

        assert len(events) == 1
        assert events[0].event_type == EventType.USER_PROMPT_SUBMITTED

    def test_unknown_event_name_falls_back_to_otlp_log(self) -> None:
        """Unrecognised event.name → OTLP_LOG with event_name + attrs preserved."""
        payload = _log_payload("claude_code.future_event", {"data": "x"})
        events = parse_otlp_logs(payload)

        assert len(events) == 1
        assert events[0].event_type == EventType.OTLP_LOG
        assert events[0].data["event_name"] == "claude_code.future_event"
        assert events[0].data["log_attrs"]["event.name"] == "claude_code.future_event"
        assert events[0].data["log_attrs"]["data"] == "x"

    def test_no_event_name_falls_back_to_otlp_log(self) -> None:
        """Log record without event.name attribute → OTLP_LOG."""
        events = parse_otlp_logs(SAMPLE_LOGS_PAYLOAD)
        assert events[0].event_type == EventType.OTLP_LOG

    def test_log_index_global_across_scopes(self) -> None:
        """Log record index is global, not per-scope — no ID collisions."""
        payload = {
            "resourceLogs": [
                {
                    "resource": {
                        "attributes": [
                            {"key": "session.id", "value": {"stringValue": "sess-1"}},
                        ]
                    },
                    "scopeLogs": [
                        {
                            "logRecords": [
                                {
                                    "timeUnixNano": "1712250005000000000",
                                    "severityText": "INFO",
                                    "body": {"stringValue": "log-a"},
                                }
                            ]
                        },
                        {
                            "logRecords": [
                                {
                                    "timeUnixNano": "1712250005000000000",
                                    "severityText": "INFO",
                                    "body": {"stringValue": "log-b"},
                                }
                            ]
                        },
                    ],
                }
            ]
        }
        events = parse_otlp_logs(payload)
        assert len(events) == 2
        assert events[0].event_id != events[1].event_id


@pytest.mark.unit
class TestNewMetricMappings:
    """Tests for newly added metric type mappings."""

    def _metric_payload(self, metric_name: str) -> dict:
        return {
            "resourceMetrics": [
                {
                    "resource": {
                        "attributes": [
                            {"key": "session.id", "value": {"stringValue": "sess-new"}},
                        ]
                    },
                    "scopeMetrics": [
                        {
                            "metrics": [
                                {
                                    "name": metric_name,
                                    "sum": {
                                        "dataPoints": [
                                            {
                                                "timeUnixNano": "1712250010000000000",
                                                "asInt": 1,
                                            }
                                        ]
                                    },
                                }
                            ]
                        }
                    ],
                }
            ]
        }

    def test_session_count_metric(self) -> None:
        """claude_code.session.count → OTLP_SESSION_COUNT (distinct from hook SESSION_STARTED)."""
        events = parse_otlp_metrics(self._metric_payload("claude_code.session.count"))
        assert len(events) == 1
        assert events[0].event_type == EventType.OTLP_SESSION_COUNT

    def test_commit_count_metric(self) -> None:
        """claude_code.commit.count → OTLP_COMMIT_COUNT (distinct from hook GIT_COMMIT)."""
        events = parse_otlp_metrics(self._metric_payload("claude_code.commit.count"))
        assert len(events) == 1
        assert events[0].event_type == EventType.OTLP_COMMIT_COUNT
