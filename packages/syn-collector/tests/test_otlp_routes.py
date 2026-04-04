"""Tests for OTLP route endpoints (/v1/metrics, /v1/logs).

Uses FastAPI TestClient with InMemoryObservabilityStore.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

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
        """Valid OTLP logs should be accepted and stored."""
        response = test_client.post("/v1/logs", json=VALID_LOGS_PAYLOAD)

        assert response.status_code == 200
        data = response.json()
        assert data["accepted"] == 1
        assert len(store.events) == 1

    def test_empty_payload(self, test_client: TestClient) -> None:
        """Empty payload should be accepted with 0."""
        response = test_client.post("/v1/logs", json={})

        assert response.status_code == 200
        assert response.json()["accepted"] == 0
