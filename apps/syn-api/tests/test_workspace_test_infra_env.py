"""An agent working ON Syntropic must be able to verify its own change (#949).

The integration suite needs Postgres and an event store. A workspace has no
Docker socket, so today the suite falls through to testcontainers and dies -
the agent can write a fix and cannot tell whether it works.

`syn_tests/fixtures/infrastructure.py` resolves explicit env vars BEFORE the
test-stack and before testcontainers, so pointing that first tier at
already-running infrastructure lets the suite run with NO container capability.
That is strictly less privilege than mediating socket access, which would still
hand the agent the host's container runtime.
"""

from __future__ import annotations

import pytest

from syn_api._wiring import _build_workspace_test_infra_env
from syn_shared.testing import (
    ENV_TEST_DATABASE_URL,
    ENV_TEST_EVENTSTORE_HOST,
    ENV_TEST_EVENTSTORE_PORT,
)

pytestmark = pytest.mark.unit

_URL = "postgres://syn:pw@timescaledb:5432/syn"


def _enable(monkeypatch: pytest.MonkeyPatch, **over: str) -> None:
    monkeypatch.setenv("SYN_WORKSPACE_TEST_INFRA_ENABLED", over.get("enabled", "true"))
    if "url" in over:
        monkeypatch.setenv("SYN_WORKSPACE_TEST_INFRA_DATABASE_URL", over["url"])
    if "host" in over:
        monkeypatch.setenv("SYN_WORKSPACE_TEST_INFRA_EVENTSTORE_HOST", over["host"])
    if "port" in over:
        monkeypatch.setenv("SYN_WORKSPACE_TEST_INFRA_EVENTSTORE_PORT", over["port"])


class TestItIsOffUnlessAskedFor:
    """This grants every workspace network reach and DB credentials. Default-on
    would be a silent privilege expansion for people who never wanted it."""

    def test_disabled_by_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("SYN_WORKSPACE_TEST_INFRA_ENABLED", raising=False)
        monkeypatch.setenv("SYN_WORKSPACE_TEST_INFRA_DATABASE_URL", _URL)
        assert _build_workspace_test_infra_env() == {}

    def test_enabled_without_a_url_injects_nothing(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Half-configured must not half-inject.

        Injecting TEST_EVENTSTORE_* without a database URL would let the suite
        start and fail on connect, which reads as a broken test rather than a
        missing setting - the expensive kind of wrong.
        """
        monkeypatch.delenv("SYN_WORKSPACE_TEST_INFRA_DATABASE_URL", raising=False)
        _enable(monkeypatch, host="eventstore", port="2113")
        import logging

        with caplog.at_level(logging.WARNING):
            assert _build_workspace_test_infra_env() == {}
        assert any("DATABASE_URL" in r.getMessage() for r in caplog.records), (
            "silently injecting nothing gives no clue why the tests still fail"
        )


class TestWhatItInjects:
    def test_the_database_url_is_passed_through(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _enable(monkeypatch, url=_URL)
        assert _build_workspace_test_infra_env()[ENV_TEST_DATABASE_URL] == _URL

    def test_the_variable_names_match_what_the_fixture_reads(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Imported from syn_shared.testing, not retyped.

        A typo here injects a variable nothing reads: the fixture silently falls
        through to testcontainers and the failure looks like missing Docker
        rather than a misspelled key.
        """
        _enable(monkeypatch, url=_URL, host="eventstore", port="2113")
        env = _build_workspace_test_infra_env()
        assert set(env) == {
            ENV_TEST_DATABASE_URL,
            ENV_TEST_EVENTSTORE_HOST,
            ENV_TEST_EVENTSTORE_PORT,
        }

    def test_the_fixture_really_reads_these_names(self) -> None:
        """Bind to the CONSUMER, not to our own constants.

        Both sides importing the same constant proves they agree with each
        other, not that either matches the fixture's resolution order. This
        asserts the fixture module actually looks these up.
        """
        from pathlib import Path

        src = Path(__import__("syn_tests.fixtures.infrastructure", fromlist=["x"]).__file__)
        body = src.read_text()
        for name in ("ENV_TEST_DATABASE_URL", "ENV_TEST_EVENTSTORE_HOST"):
            assert name in body, f"{name} is not consulted by the test fixture"

    def test_an_unset_eventstore_port_is_omitted_not_zeroed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`TEST_EVENTSTORE_PORT=0` is worse than absent: the fixture would use
        it verbatim and connect to port 0 instead of falling back."""
        monkeypatch.delenv("SYN_WORKSPACE_TEST_INFRA_EVENTSTORE_PORT", raising=False)
        _enable(monkeypatch, url=_URL)
        assert ENV_TEST_EVENTSTORE_PORT not in _build_workspace_test_infra_env()
