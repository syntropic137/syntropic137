"""Tests for OTLP route endpoints (/v1/metrics, /v1/logs).

Uses FastAPI TestClient with InMemoryObservabilityStore.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from syn_collector.collector.dedup import DeduplicationFilter
from syn_collector.collector.service import create_app
from syn_collector.collector.store import InMemoryObservabilityStore


@pytest.fixture
def store() -> InMemoryObservabilityStore:
    """Create a fresh in-memory store."""
    return InMemoryObservabilityStore()


@pytest.fixture
def test_client(store: InMemoryObservabilityStore) -> TestClient:
    """Create test client with accessible store."""
    app = create_app(store=store)
    return TestClient(app)


VALID_METRICS_PAYLOAD = {
    "resourceMetrics": [
        {
            "resource": {
                "attributes": [
                    {"key": "session.id", "value": {"stringValue": "sess-test"}},
                ]
            },
            "scopeMetrics": [
                {
                    "metrics": [
                        {
                            "name": "claude_code.token.usage",
                            "gauge": {
                                "dataPoints": [
                                    {
                                        "timeUnixNano": "1712250000000000000",
                                        "asInt": 500,
                                        "attributes": [],
                                    },
                                ],
                            },
                        },
                    ],
                }
            ],
        }
    ]
}

VALID_LOGS_PAYLOAD = {
    "resourceLogs": [
        {
            "resource": {
                "attributes": [
                    {"key": "session.id", "value": {"stringValue": "sess-test"}},
                ]
            },
            "scopeLogs": [
                {
                    "logRecords": [
                        {
                            "timeUnixNano": "1712250002000000000",
                            "severityText": "INFO",
                            "body": {"stringValue": "test log message"},
                        },
                    ],
                }
            ],
        }
    ]
}


@pytest.mark.unit
class TestOtlpMetricsEndpoint:
    """Tests for POST /v1/metrics."""

    def test_valid_payload_accepted(
        self, test_client: TestClient, store: InMemoryObservabilityStore
    ) -> None:
        """Valid OTLP metrics should be accepted and stored."""
        response = test_client.post("/v1/metrics", json=VALID_METRICS_PAYLOAD)

        assert response.status_code == 200
        data = response.json()
        assert data["accepted"] == 1
        assert len(store.events) == 1
        assert store.events[0]["event_type"] == "token_usage"

    def test_empty_resource_metrics(self, test_client: TestClient) -> None:
        """Empty resourceMetrics should be accepted with 0."""
        response = test_client.post("/v1/metrics", json={"resourceMetrics": []})

        assert response.status_code == 200
        assert response.json()["accepted"] == 0

    def test_invalid_json(self, test_client: TestClient) -> None:
        """Non-JSON body should return 400."""
        response = test_client.post(
            "/v1/metrics",
            content=b"not json",
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 400

    def test_dedup_prevents_duplicates(
        self, test_client: TestClient, store: InMemoryObservabilityStore
    ) -> None:
        """Same metrics sent twice should be deduped."""
        test_client.post("/v1/metrics", json=VALID_METRICS_PAYLOAD)
        test_client.post("/v1/metrics", json=VALID_METRICS_PAYLOAD)

        assert len(store.events) == 1  # Second batch deduped


@pytest.mark.unit
class TestOtlpLogsEndpoint:
    """Tests for POST /v1/logs."""

    def test_valid_payload_accepted(
        self, test_client: TestClient, store: InMemoryObservabilityStore
    ) -> None:
        """Valid OTLP logs should be accepted and stored as OTLP_LOG events."""
        response = test_client.post("/v1/logs", json=VALID_LOGS_PAYLOAD)

        assert response.status_code == 200
        data = response.json()
        assert data["accepted"] == 1
        assert len(store.events) == 1
        assert store.events[0]["event_type"] == "otlp_log"

    def test_empty_payload(self, test_client: TestClient) -> None:
        """Empty payload should be accepted with 0."""
        response = test_client.post("/v1/logs", json={})

        assert response.status_code == 200
        assert response.json()["accepted"] == 0


@pytest.mark.unit
class TestOtlpPayloadValidation:
    """Tests for payload type validation in OTLP endpoints."""

    def test_array_payload_returns_400(self, test_client: TestClient) -> None:
        """Sending a JSON array instead of object should return 400."""
        response = test_client.post("/v1/metrics", json=[1, 2, 3])

        assert response.status_code == 400
        assert response.json()["error"] == "Payload must be a JSON object"

    def test_string_payload_returns_400(self, test_client: TestClient) -> None:
        """Sending a JSON string instead of object should return 400."""
        response = test_client.post("/v1/logs", json="not an object")

        assert response.status_code == 400
        assert response.json()["error"] == "Payload must be a JSON object"

    def test_number_payload_returns_400(self, test_client: TestClient) -> None:
        """Sending a JSON number instead of object should return 400."""
        response = test_client.post("/v1/metrics", json=42)

        assert response.status_code == 400
        assert response.json()["error"] == "Payload must be a JSON object"


@pytest.mark.unit
class TestDedupWriteFailureSafety:
    """Tests that write failures don't permanently mark events as seen."""

    @pytest.mark.asyncio
    async def test_write_failure_allows_retry(self) -> None:
        """If write_event fails, the event should NOT be marked as seen."""
        from datetime import UTC, datetime

        from syn_collector.collector.routes import _write_deduped
        from syn_collector.events.types import CollectedEvent, EventType

        event = CollectedEvent(
            event_id="evt-fail-001-abcdef01",
            event_type=EventType.TOKEN_USAGE,
            session_id="sess-test",
            timestamp=datetime.now(UTC),
            data={"source": "otlp", "metric_name": "test", "value": 1},
        )

        failing_store = AsyncMock()
        failing_store.write_event = AsyncMock(side_effect=RuntimeError("DB down"))
        dedup = DeduplicationFilter()

        # First attempt: write fails
        accepted = await _write_deduped([event], failing_store, dedup, "test")
        assert accepted == 0
        assert dedup.is_seen(event.event_id) is False  # NOT marked as seen

        # Second attempt: write succeeds (retry safe)
        working_store = AsyncMock()
        working_store.write_event = AsyncMock()
        accepted = await _write_deduped([event], working_store, dedup, "test")
        assert accepted == 1
        assert dedup.is_seen(event.event_id) is True  # Now marked

    @pytest.mark.asyncio
    async def test_successful_write_marks_seen(self) -> None:
        """After successful write, event should be marked as seen."""
        from datetime import UTC, datetime

        from syn_collector.collector.routes import _write_deduped
        from syn_collector.events.types import CollectedEvent, EventType

        event = CollectedEvent(
            event_id="evt-ok-001-abcdef0123",
            event_type=EventType.TOKEN_USAGE,
            session_id="sess-test",
            timestamp=datetime.now(UTC),
            data={"source": "otlp", "metric_name": "test", "value": 1},
        )

        mock_store: Any = AsyncMock()
        mock_store.write_event = AsyncMock()
        dedup = DeduplicationFilter()

        accepted = await _write_deduped([event], mock_store, dedup, "test")
        assert accepted == 1
        assert dedup.is_seen(event.event_id) is True
