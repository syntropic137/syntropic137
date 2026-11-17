"""Pins what the typed OTLP envelope (otlp_envelope.py) hands downstream.

The envelope replaced dict lookups in otlp.py (#673). These tests assert on
what consumes it, the CollectedEvent the parser builds and the row the
/v1/metrics and /v1/logs routes store, so a renamed field or alias, a changed
precedence or a coerced value fails here rather than silently changing
stored observability data.
"""

from __future__ import annotations

import hashlib

import pytest
from fastapi.testclient import TestClient

from syn_collector.collector.otlp import parse_otlp_logs, parse_otlp_metrics
from syn_collector.collector.service import create_app
from syn_collector.collector.store import InMemoryObservabilityStore
from syn_collector.events.types import EventType

SESSION = {"attributes": [{"key": "session.id", "value": {"stringValue": "sess-env"}}]}

# Every scalar AnyValue kind, a key repeated (last wins, first position kept),
# and a value with no recognised kind.
ATTRIBUTES = [
    {"key": "type", "value": {"stringValue": "input"}},
    {"key": "count", "value": {"intValue": "5"}},
    {"key": "ratio", "value": {"doubleValue": 3}},
    {"key": "flag", "value": {"boolValue": False}},
    {"key": "blank", "value": {}},
    {"key": "type", "value": {"stringValue": "output"}},
]


def _event_id(session_id: str, name: str, timestamp: str, index: int) -> str:
    content = f"otlp:{session_id}:{name}:{timestamp}:{index}"
    return hashlib.sha256(content.encode()).hexdigest()[:32]


def _metrics(metric: dict[str, object]) -> dict[str, object]:
    return {"resourceMetrics": [{"resource": SESSION, "scopeMetrics": [{"metrics": [metric]}]}]}


def _logs(record: dict[str, object]) -> dict[str, object]:
    return {"resourceLogs": [{"resource": SESSION, "scopeLogs": [{"logRecords": [record]}]}]}


@pytest.mark.unit
class TestMetricsEnvelope:
    def test_datapoint_event_shape(self) -> None:
        payload = _metrics(
            {
                "name": "claude_code.token.usage",
                "unit": "tokens",
                "sum": {
                    "aggregationTemporality": 2,
                    "dataPoints": [
                        {
                            "timeUnixNano": "1712250000000000000",
                            "startTimeUnixNano": "1712249000000000000",
                            "asInt": "12",
                            "attributes": ATTRIBUTES,
                        }
                    ],
                },
            }
        )
        [event] = parse_otlp_metrics(payload)
        assert event.event_type == EventType.TOKEN_USAGE
        assert event.session_id == "sess-env"
        assert event.event_id == _event_id(
            "sess-env", "claude_code.token.usage", "1712250000000000000", 0
        )
        assert list(event.data.items()) == [
            ("source", "otlp"),
            ("metric_name", "claude_code.token.usage"),
            ("value", "12"),
            ("type", "output"),
            ("count", "5"),
            ("ratio", 3),
            ("flag", False),
            ("blank", ""),
        ]
        # Not coerced: int64 stays a string, a whole double stays an int.
        assert type(event.data["value"]) is str
        assert type(event.data["ratio"]) is int

    @pytest.mark.parametrize(
        ("point", "expected"),
        [
            ({"asDouble": 1.5, "asInt": "3"}, 1.5),
            ({"asInt": "3", "as_double": 2.0}, "3"),
            ({"as_double": 2.0, "as_int": 4}, 2.0),
            ({"as_int": 4}, 4),
            ({}, 0),
        ],
    )
    def test_value_precedence(self, point: dict[str, object], expected: object) -> None:
        payload = _metrics({"name": "claude_code.cost.usage", "gauge": {"dataPoints": [point]}})
        [event] = parse_otlp_metrics(payload)
        assert event.data["value"] == expected
        assert type(event.data["value"]) is type(expected)

    def test_snake_case_key_wins_over_camel_case(self) -> None:
        payload = _metrics(
            {
                "name": "claude_code.cost.usage",
                "gauge": {
                    "data_points": [{"time_unix_nano": "1712250000000000000", "timeUnixNano": "9"}],
                    "dataPoints": [{}, {}],
                },
            }
        )
        [event] = parse_otlp_metrics(payload)
        assert event.event_id == _event_id(
            "sess-env", "claude_code.cost.usage", "1712250000000000000", 0
        )

    def test_empty_section_falls_through_to_next(self) -> None:
        payload = _metrics(
            {
                "name": "claude_code.commit.count",
                "gauge": {},
                "sum": {"dataPoints": [{"asInt": "1"}]},
            }
        )
        assert [e.data["value"] for e in parse_otlp_metrics(payload)] == ["1"]

    def test_non_empty_section_without_points_does_not_fall_through(self) -> None:
        payload = _metrics(
            {
                "name": "claude_code.commit.count",
                "gauge": {"aggregationTemporality": 2},
                "sum": {"dataPoints": [{"asInt": "1"}]},
            }
        )
        assert parse_otlp_metrics(payload) == []

    def test_session_id_needs_a_string_value(self) -> None:
        payload = {
            "resourceMetrics": [
                {
                    "resource": {"attributes": [{"key": "session.id", "value": {"intValue": "7"}}]},
                    "scopeMetrics": [
                        {
                            "metrics": [
                                {"name": "claude_code.cost.usage", "gauge": {"dataPoints": [{}]}}
                            ]
                        }
                    ],
                },
                {
                    "scopeMetrics": [
                        {
                            "metrics": [
                                {"name": "claude_code.cost.usage", "gauge": {"dataPoints": [{}]}}
                            ]
                        }
                    ]
                },
            ]
        }
        assert [e.session_id for e in parse_otlp_metrics(payload)] == ["unknown", "unknown"]


@pytest.mark.unit
class TestLogsEnvelope:
    def test_known_event_shape(self) -> None:
        payload = _logs(
            {
                "timeUnixNano": "1712250002000000000",
                "traceId": "abc",
                "severityText": "WARN",
                "attributes": [
                    {"key": "event.name", "value": {"stringValue": "claude_code.api_request"}},
                    {"key": "cost_usd", "value": {"doubleValue": 0.25}},
                    {"key": "input_tokens", "value": {"intValue": "40"}},
                ],
            }
        )
        [event] = parse_otlp_logs(payload)
        assert event.event_type == EventType.API_REQUEST
        assert event.event_id == _event_id(
            "sess-env", "claude_code.api_request", "1712250002000000000", 0
        )
        assert event.data == {
            "source": "otlp",
            "event.name": "claude_code.api_request",
            "cost_usd": 0.25,
            "input_tokens": "40",
        }

    def test_unknown_event_shape_is_bounded(self) -> None:
        payload = _logs(
            {
                "time_unix_nano": "1712250003000000000",
                "severity_text": "ERROR",
                "severityText": "INFO",
                "body": {"stringValue": "b" * 2500},
                "attributes": [
                    {"key": f"k{i}", "value": {"stringValue": "v" * 600}} for i in range(55)
                ],
            }
        )
        [event] = parse_otlp_logs(payload)
        assert event.event_type == EventType.OTLP_LOG
        assert event.event_id == _event_id("sess-env", "log", "1712250003000000000", 0)
        assert list(event.data) == ["source", "severity", "body", "event_name", "log_attrs"]
        assert event.data["severity"] == "ERROR"
        assert event.data["body"] == "b" * 2000
        assert event.data["event_name"] == ""
        assert event.data["log_attrs"] == {f"k{i}": "v" * 500 for i in range(50)}

    def test_defaults_when_record_is_bare(self) -> None:
        [event] = parse_otlp_logs(_logs({}))
        assert event.data == {
            "source": "otlp",
            "severity": "INFO",
            "body": "",
            "event_name": "",
            "log_attrs": {},
        }


@pytest.mark.unit
class TestStoredRows:
    """The row the routes hand the store, end to end through the envelope."""

    @pytest.fixture
    def store(self) -> InMemoryObservabilityStore:
        return InMemoryObservabilityStore()

    @pytest.fixture
    def client(self, store: InMemoryObservabilityStore) -> TestClient:
        return TestClient(create_app(store=store))

    def test_metrics_row(self, client: TestClient, store: InMemoryObservabilityStore) -> None:
        payload = _metrics(
            {
                "name": "claude_code.token.usage",
                "gauge": {
                    "dataPoints": [
                        {
                            "timeUnixNano": "1712250000000000000",
                            "asInt": "500",
                            "attributes": [{"key": "type", "value": {"stringValue": "input"}}],
                        }
                    ]
                },
            }
        )
        assert client.post("/v1/metrics", json=payload).status_code == 200
        assert store.events == [
            {
                "source": "otlp",
                "metric_name": "claude_code.token.usage",
                "value": "500",
                "type": "input",
                "event_type": "token_usage",
                "session_id": "sess-env",
                "timestamp": "2024-04-04T17:00:00+00:00",
                "event_id": _event_id(
                    "sess-env", "claude_code.token.usage", "1712250000000000000", 0
                ),
            }
        ]

    def test_logs_row(self, client: TestClient, store: InMemoryObservabilityStore) -> None:
        payload = _logs(
            {
                "timeUnixNano": "1712250002000000000",
                "severityText": "INFO",
                "body": {"stringValue": "hello"},
                "attributes": [{"key": "n", "value": {"intValue": "3"}}],
            }
        )
        assert client.post("/v1/logs", json=payload).status_code == 200
        assert store.events == [
            {
                "source": "otlp",
                "severity": "INFO",
                "body": "hello",
                "event_name": "",
                "log_attrs": {"n": "3"},
                "event_type": "otlp_log",
                "session_id": "sess-env",
                "timestamp": "2024-04-04T17:00:02+00:00",
                "event_id": _event_id("sess-env", "log", "1712250002000000000", 0),
            }
        ]
