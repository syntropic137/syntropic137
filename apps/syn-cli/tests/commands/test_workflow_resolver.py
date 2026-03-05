"""Tests for WorkflowResolver."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from click.exceptions import Exit

from syn_cli.commands._workflow_resolver import WorkflowResolver


def _mock_client(workflows: list[dict]) -> MagicMock:  # type: ignore[type-arg]
    """Create a mock httpx.Client returning given workflows."""
    client = MagicMock()
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"workflows": workflows}
    client.get.return_value = resp
    return client


@pytest.mark.unit
class TestWorkflowResolver:
    def test_resolve_exact_match(self) -> None:
        client = _mock_client(
            [
                {"id": "abc-123", "name": "Test", "workflow_type": "custom", "phase_count": 2},
            ]
        )
        wf = WorkflowResolver(client).resolve("abc-123")
        assert wf.id == "abc-123"
        assert wf.name == "Test"

    def test_resolve_partial_match(self) -> None:
        client = _mock_client(
            [
                {"id": "abc-123", "name": "Test", "workflow_type": "custom"},
            ]
        )
        wf = WorkflowResolver(client).resolve("abc")
        assert wf.id == "abc-123"

    def test_resolve_no_match_exits(self) -> None:
        client = _mock_client([])
        with pytest.raises(Exit):
            WorkflowResolver(client).resolve("xyz")

    def test_resolve_ambiguous_exits(self) -> None:
        client = _mock_client(
            [
                {"id": "abc-1", "name": "A", "workflow_type": "custom"},
                {"id": "abc-2", "name": "B", "workflow_type": "custom"},
            ]
        )
        with pytest.raises(Exit):
            WorkflowResolver(client).resolve("abc")
