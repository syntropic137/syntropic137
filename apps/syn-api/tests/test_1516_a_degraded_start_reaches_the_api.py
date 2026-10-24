"""A workspace that started with capture off reads as degraded, end to end (#1516).

Drives the real `SessionCaptureService` - with the real agentic-workspace
reader behind it - against a fake container, hands what it wrote to the real
`/capture/status` route, and asserts on the response. The value is written in
one package and read in another; a test of either end alone would pass with
the field dropped at the hop between them.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from syn_adapters.workspace_backends.agentic.session_capture_service import (
    SessionCaptureService,
)
from syn_api.routes.capture import get_capture_status
from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
    ExecutionResult,
)
from syn_shared.settings.session_store import SessionStoreSettings

if TYPE_CHECKING:
    from pydantic import JsonValue

_STORE = "http://store:8799"
_HOST = "ws-host-1"

#: What the exporter prints when capture was switched off at start: it ran,
#: discovered nothing, and stored nothing.
_EMPTY_SWEEP = json.dumps(
    {
        "schema_version": 1,
        "captured_everything": True,
        "store_url": _STORE,
        "origin": {"environment": "container", "deployment": "syntropic137__dev"},
        "counters": {"discovered": 0, "uploaded": 0, "accepted": 0},
    }
)

_CLEAN = json.dumps(
    {
        "schema_version": 1,
        "captured_everything": True,
        "store_url": _STORE,
        "origin": {"environment": "container", "deployment": "syntropic137__dev"},
        "counters": {"discovered": 1, "uploaded": 1, "accepted": 1},
    }
)


def _status_row(status: str, failed_checks: list[str], doctor_exit: int) -> str:
    """One `capability_status` row as the agentic-workspace entrypoint writes it."""
    return json.dumps(
        {
            "schema_version": 1,
            "record": "capability_status",
            "capability": "session-store",
            "provider": "apss",
            "status": status,
            "policy": "degrade",
            "required": False,
            "doctor_exit": doctor_exit,
            "failed_checks": failed_checks,
            "host": _HOST,
            "at": "2026-10-24T00:00:00Z",
        },
        separators=(",", ":"),
    )


def _container(*, status_row: str | None, exporter_stdout: str, read_breaks: bool = False):
    """A running workspace: answers the status read and the exporter."""

    async def _exec(
        command: list[str], *, timeout_seconds: int, environment=None
    ) -> ExecutionResult:
        if command[:2] == ["sh", "-c"] and "capability_status" in command[2]:
            if read_breaks:
                raise TimeoutError("docker exec timed out")
            rows = f"{status_row}\n" if status_row else ""
            stdout = f"{_HOST}\n{rows}"
        else:
            stdout = exporter_stdout
        return ExecutionResult(exit_code=0, success=True, duration_ms=1.0, stdout=stdout)

    return _exec


class _Recorder:
    """The observation writer and the route's store, sharing one table."""

    def __init__(self) -> None:
        self.rows: list[dict[str, JsonValue]] = []

    async def record_observation(self, **kwargs: object) -> None:
        # Flattened and JSON round-tripped, as query_by_execution returns it.
        data: dict[str, JsonValue] = json.loads(json.dumps(kwargs["data"]))
        self.rows.append(
            {
                "timestamp": "2026-10-24T00:00:01+00:00",
                "event_type": str(kwargs["observation_type"]),
                "session_id": str(kwargs["session_id"]),
                "execution_id": str(kwargs["execution_id"]),
                "phase_id": str(kwargs["phase_id"]),
                **data,
            }
        )

    async def query_by_execution(
        self, execution_id: str, event_type: str | None = None, limit: int = 1000
    ) -> list[dict[str, JsonValue]]:
        return [
            row
            for row in self.rows
            if row["execution_id"] == execution_id and row["event_type"] == event_type
        ][:limit]


async def _run(
    monkeypatch: pytest.MonkeyPatch,
    *,
    status_row: str | None,
    exporter_stdout: str,
    url: str | None = _STORE,
    read_breaks: bool = False,
):
    recorder = _Recorder()
    service = SessionCaptureService(SessionStoreSettings(url=url), "dev", recorder)
    await service.capture_and_record(
        _container(status_row=status_row, exporter_stdout=exporter_stdout, read_breaks=read_breaks),
        session_id="s-1",
        execution_id="e-1",
        workspace_id="w-1",
        phase_id="p-1",
        expect_sessions=True,
    )
    monkeypatch.setattr("syn_api.routes.capture.get_event_store", lambda: recorder)
    return await get_capture_status(limit=50, needs_backfill=False, execution_id="e-1")


@pytest.mark.unit
class TestADegradedStartIsExplained:
    @pytest.mark.asyncio
    async def test_the_api_names_the_failed_check(self, monkeypatch: pytest.MonkeyPatch) -> None:
        response = await _run(
            monkeypatch,
            status_row=_status_row("degraded", ["store_reachable"], 3),
            exporter_stdout=_EMPTY_SWEEP,
        )

        [entry] = response.entries
        assert entry.state == "degraded"
        assert entry.capability_status == "degraded"
        assert entry.failed_checks == ["store_reachable"]
        assert entry.doctor_exit == 3
        assert entry.capture_status_display == "Capture degraded: store_reachable failed"
        # Still not in the store, so still work - but now explained work.
        assert entry.needs_backfill is True

    @pytest.mark.asyncio
    async def test_a_degraded_start_outranks_a_clean_looking_sweep(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        response = await _run(
            monkeypatch,
            status_row=_status_row("degraded", ["auth_valid"], 2),
            exporter_stdout=_CLEAN,
        )

        [entry] = response.entries
        assert entry.state == "degraded"
        assert entry.capture_status_display == "Capture degraded: auth_valid failed"


@pytest.mark.unit
class TestNothingNewOtherwise:
    @pytest.mark.asyncio
    async def test_a_healthy_store_reads_as_captured_and_ready(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        response = await _run(
            monkeypatch,
            status_row=_status_row("ready", [], 0),
            exporter_stdout=_CLEAN,
        )

        [entry] = response.entries
        assert entry.state == "captured"
        assert entry.capability_status == "ready"
        assert entry.capture_status_display == "Captured"

    @pytest.mark.asyncio
    async def test_no_store_configured_records_nothing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        response = await _run(monkeypatch, status_row=None, exporter_stdout=_EMPTY_SWEEP, url=None)

        assert response.entries == []

    @pytest.mark.asyncio
    async def test_an_unreadable_status_is_unknown_not_degraded(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        response = await _run(
            monkeypatch,
            status_row=_status_row("degraded", ["store_reachable"], 3).replace(
                '"doctor_exit":3', '"doctor_exit":-1'
            ),
            exporter_stdout=_CLEAN,
        )

        [entry] = response.entries
        assert entry.state == "captured"
        assert entry.capability_status is None

    @pytest.mark.asyncio
    async def test_a_broken_status_read_still_records_the_capture(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Fail-open: the exec breaking is unknown, not a lost capture verdict."""
        response = await _run(
            monkeypatch, status_row=None, exporter_stdout=_CLEAN, read_breaks=True
        )

        [entry] = response.entries
        assert entry.state == "captured"
        assert entry.capability_status is None
