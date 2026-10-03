"""The UI feedback feature flag, from both sides (ADR-016, #105).

``SYN_UI_FEEDBACK_ENABLED`` is off by default and off is the open-source
posture, so "off" is not an absence of behaviour to be assumed - it is
behaviour with its own assertions: no storage is built (so no feedback
tables are created), every feedback route answers a typed 404, and the
features endpoint says so to the dashboard.

The routes themselves exist in both states on purpose. Their presence in
the OpenAPI spec is asserted to be flag-independent, because the spec is
committed and drives the generated CLI and dashboard types: if the mount
moved with the flag, two deployments of the same image would disagree
about the contract.

See ``syn_api.services.ui_feedback`` - the one place the feature is decided.
"""

from __future__ import annotations

import io
import os
from contextlib import asynccontextmanager, contextmanager
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

from syn_adapters.in_memory import InMemoryAdapterError
from syn_api.types import FeatureDisabledResponse

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator

# CI runs `pytest -m unit`; an unmarked module collects zero tests and the
# gate goes green having run none of them (#1065).
pytestmark = pytest.mark.unit


os.environ.setdefault("APP_ENVIRONMENT", "test")


@contextmanager
def configured(
    *,
    enabled: bool,
    environment: str = "test",
    db_url: str = "",
) -> Iterator[None]:
    """Run a block against a specific feature configuration.

    Settings are cached, and ``ui_feedback`` holds a process-global storage
    handle, so both are reset on the way in and on the way out - otherwise
    one test's flag would leak into the next.
    """
    from syn_api.services import ui_feedback
    from syn_shared.settings import reset_settings

    previous = {
        key: os.environ.get(key)
        for key in ("SYN_UI_FEEDBACK_ENABLED", "APP_ENVIRONMENT", "SYN_OBSERVABILITY_DB_URL")
    }
    os.environ["SYN_UI_FEEDBACK_ENABLED"] = "true" if enabled else "false"
    os.environ["APP_ENVIRONMENT"] = environment
    os.environ["SYN_OBSERVABILITY_DB_URL"] = db_url
    reset_settings()
    ui_feedback.reset_for_tests()
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        reset_settings()
        ui_feedback.reset_for_tests()


def _client() -> TestClient:
    from syn_api.main import create_app

    return TestClient(create_app())


# =====================================================================
# Off - the open-source default
# =====================================================================


def test_features_endpoint_reports_the_feature_off():
    """The dashboard learns the flag at runtime, from the API."""
    with configured(enabled=False):
        response = _client().get("/features")

    assert response.status_code == 200
    assert response.json() == {"ui_feedback": False}


def test_standard_install_without_feedback_package_still_starts(monkeypatch):
    """The API's base install does not require the optional feedback extra."""
    import importlib.util

    import syn_api.main as main

    actual_find_spec = importlib.util.find_spec
    monkeypatch.setattr(
        importlib.util,
        "find_spec",
        lambda name: None if name == "ui_feedback" else actual_find_spec(name),
    )
    with configured(enabled=False):
        app = main.create_app()
        assert TestClient(app).get("/features").json() == {"ui_feedback": False}
        assert "/feedback" not in app.openapi()["paths"]

    with configured(enabled=True), pytest.raises(RuntimeError, match="syn-api\\[feedback\\]"):
        main.create_app()


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/feedback"),
        ("POST", "/feedback"),
        ("GET", "/feedback/stats"),
        ("GET", "/feedback/00000000-0000-0000-0000-000000000000"),
    ],
)
def test_feedback_routes_answer_a_typed_404_when_disabled(method: str, path: str):
    """Disabled is a contract, not a crash: a typed 404 naming the flag."""
    with configured(enabled=False):
        response = _client().request(method, path, json={})

    assert response.status_code == 404
    # Parses under the model the route advertises for 404 - the dashboard and
    # the CLI are entitled to rely on the shape, not just the status code.
    body = FeatureDisabledResponse.model_validate(response.json())
    assert body.detail.feature == "ui_feedback"
    assert body.detail.enable_with == "SYN_UI_FEEDBACK_ENABLED=true"


async def test_disabled_startup_builds_no_storage_and_creates_no_tables():
    """Off means the migration never runs - not that it runs and is unused."""
    from syn_api.services import ui_feedback

    built = False

    def _explode() -> object:
        nonlocal built
        built = True
        raise AssertionError("storage must not be built while the feature is disabled")

    with configured(enabled=False):
        original = ui_feedback._build_storage
        ui_feedback._build_storage = _explode  # type: ignore[assignment]
        try:
            await ui_feedback.connect()
        finally:
            ui_feedback._build_storage = original  # type: ignore[assignment]

        assert built is False
        assert ui_feedback._storage is None


# =====================================================================
# The contract does not move with the flag
# =====================================================================


def test_the_openapi_spec_is_identical_in_both_states():
    """The committed spec, the CLI types and check:api-drift must not care."""
    with configured(enabled=False):
        off = _client().get("/openapi.json").json()
    with configured(enabled=True):
        on = _client().get("/openapi.json").json()

    assert off == on
    assert "/feedback" in off["paths"]
    assert "/feedback/{feedback_id}/media" in off["paths"]


# =====================================================================
# Storage selection - never in-memory in production (ADR-060)
# =====================================================================


def test_enabled_without_a_durable_database_refuses_to_start():
    """Fail fast beats silently dropping every item on the next restart."""
    from syn_api.services.ui_feedback import UiFeedbackConfigurationError, _build_storage

    with (
        configured(enabled=True, environment="production"),
        pytest.raises(UiFeedbackConfigurationError, match="SYN_OBSERVABILITY_DB_URL"),
    ):
        _build_storage()


def test_in_memory_storage_refuses_to_exist_outside_test_or_offline():
    """The guard is at construction, so no path reaches production holding one."""
    from syn_api.services.ui_feedback import TestOnlyFeedbackStorage

    with configured(enabled=True, environment="production"), pytest.raises(InMemoryAdapterError):
        TestOnlyFeedbackStorage()


def test_a_durable_database_url_selects_postgres():
    """The production path, with no connection attempted."""
    from ui_feedback.storage.postgres import PostgresFeedbackStorage

    from syn_api.services.ui_feedback import _build_storage

    with configured(
        enabled=True,
        environment="production",
        db_url="postgresql://syn:syn@db:5432/syn",
    ):
        storage = _build_storage()

    assert isinstance(storage, PostgresFeedbackStorage)


# =====================================================================
# On - the owner's deployment
# =====================================================================


class _RecordingConnection:
    """Records the SQL a migration run issues, executing none of it."""

    def __init__(self, statements: list[str]) -> None:
        self._statements = statements

    async def execute(self, sql: str) -> None:
        self._statements.append(sql)


class _RecordingPool:
    """Stands in for an asyncpg pool. Only what a migration run touches."""

    def __init__(self) -> None:
        self.statements: list[str] = []

    @asynccontextmanager
    async def acquire(self) -> AsyncIterator[_RecordingConnection]:
        yield _RecordingConnection(self.statements)

    async def close(self) -> None:
        return None


async def test_enabling_it_needs_no_migration_command_only_a_restart(monkeypatch):
    """Setting the flag and booting is the whole of the operator's work.

    The claim being pinned is the operator instruction in the README and the
    PR body: one .env line plus a restart. So this drives the actual startup
    path - the same ``connect()`` lifecycle.py calls - rather than reaching
    into the storage object, and asserts the schema arrived on the way. If
    the migration ever moves behind an explicit command, or auto_migrate is
    defaulted off at the point where syn-api constructs the storage, the
    tables stop appearing here and the operator silently gets a deployment
    whose feedback routes 500 on a missing table.

    A real database is not needed to see this and would hide it in an
    integration marker that the unit sweep never runs. The Postgres round
    trip in tests/integration covers what only a real server can show.
    """
    import asyncpg

    from syn_api.services import ui_feedback

    pool = _RecordingPool()

    async def _fake_create_pool(*_args: object, **_kwargs: object) -> _RecordingPool:
        return pool

    monkeypatch.setattr(asyncpg, "create_pool", _fake_create_pool)

    with configured(
        enabled=True,
        environment="production",
        db_url="postgresql://syn:syn@db:5432/syn",
    ):
        await ui_feedback.connect()
        await ui_feedback.disconnect()

    applied = "\n".join(pool.statements)
    assert "CREATE TABLE IF NOT EXISTS feedback_items" in applied
    assert "CREATE TABLE IF NOT EXISTS feedback_media" in applied
    # 002 must be in there too - applying only 001 is the failure that looks
    # like success until something reads subject_id.
    assert "ADD COLUMN IF NOT EXISTS subject_kind" in applied

    # Every restart after the first re-applies all of it, so a statement that
    # is not idempotent turns the second boot into a crash loop. Split on
    # statements, not lines: `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` puts
    # the guard on a later line than the verb.
    without_comments = "\n".join(
        line for line in applied.splitlines() if not line.lstrip().startswith("--")
    )
    creates = [
        " ".join(statement.split())
        for statement in without_comments.split(";")
        if statement.strip().upper().startswith(("CREATE TABLE", "CREATE INDEX", "ALTER TABLE"))
    ]
    assert creates
    for statement in creates:
        assert "IF NOT EXISTS" in statement.upper(), statement


async def test_enabled_round_trip_through_the_api():
    """Create with a screenshot, filter the list, move the status on."""
    from syn_api.services import ui_feedback

    with configured(enabled=True):
        await ui_feedback.connect()
        try:
            client = _client()

            assert client.get("/features").json() == {"ui_feedback": True}

            created = client.post(
                "/feedback",
                json={
                    "url": "http://localhost:9137/executions/exec-1",
                    "route": "/executions/exec-1",
                    "subject_kind": "execution",
                    "subject_id": "exec-1",
                    "feedback_type": "bug",
                    "comment": "The phase timer keeps running after it finishes.",
                    "app_name": "syn-dashboard-ui",
                },
            )
            assert created.status_code == 201, created.text
            feedback_id = created.json()["id"]

            uploaded = client.post(
                f"/feedback/{feedback_id}/media",
                files={"file": ("shot.png", io.BytesIO(b"\x89PNG\r\n\x1a\n"), "image/png")},
                data={"media_type": "screenshot"},
            )
            assert uploaded.status_code == 201, uploaded.text

            # Active content cannot be stored under an image MIME type and
            # served from the authenticated dashboard origin.
            rejected = client.post(
                f"/feedback/{feedback_id}/media",
                files={
                    "file": (
                        "malicious.svg",
                        io.BytesIO(b"<svg onload='alert(1)'/>"),
                        "image/svg+xml",
                    )
                },
                data={"media_type": "screenshot"},
            )
            assert rejected.status_code == 400

            # Filterable by the things an agent triages on.
            listed = client.get("/feedback", params={"route": "/executions/exec-1"}).json()
            assert [item["id"] for item in listed["items"]] == [feedback_id]
            assert listed["items"][0]["media_count"] == 1

            assert client.get("/feedback", params={"subject_id": "exec-1"}).json()["total"] == 1
            assert client.get("/feedback", params={"subject_id": "other"}).json()["total"] == 0
            assert client.get("/feedback", params={"status": "resolved"}).json()["total"] == 0

            patched = client.patch(f"/feedback/{feedback_id}", json={"status": "resolved"})
            assert patched.status_code == 200, patched.text
            assert patched.json()["status"] == "resolved"

            assert client.get("/feedback", params={"status": "resolved"}).json()["total"] == 1
        finally:
            await ui_feedback.disconnect()


async def test_an_oversized_upload_is_refused():
    """The host's ceiling, not the vendored module's, is the one in force."""
    from syn_api.services import ui_feedback

    with configured(enabled=True):
        await ui_feedback.connect()
        try:
            client = _client()
            created = client.post(
                "/feedback",
                json={"url": "http://localhost:9137/", "app_name": "syn-dashboard-ui"},
            )
            feedback_id = created.json()["id"]

            oversized = io.BytesIO(b"0" * (ui_feedback.MAX_UPLOAD_BYTES + 1))
            response = client.post(
                f"/feedback/{feedback_id}/media",
                files={"file": ("big.webm", oversized, "audio/webm")},
                data={"media_type": "voice_note"},
            )

            assert response.status_code == 413
        finally:
            await ui_feedback.disconnect()
