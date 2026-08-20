"""Startup must say whether session capture is configured, and for which deployment.

Capture is a per-workspace concern, so before this its posture was only
observable after a workflow ran. An operator who configured a store and never
started one saw nothing - and the most common misconfiguration (URL set, token
missing) fails at finalize with a suppressed diagnostic, producing a failure
count with no cause.
"""

from __future__ import annotations

import logging

import pytest

from syn_adapters.workspace_backends.agentic.session_store_env import (
    deployment_identity,
)
from syn_api.services.lifecycle import _log_session_capture_posture
from syn_api.types import Err
from syn_shared.settings.config import AppEnvironment
from syn_shared.settings.session_store import SessionStoreSettings

STORE = "https://sessions.example.com"
TOKEN = "super-secret-write-token"


def _posture(
    caplog: pytest.LogCaptureFixture,
    app_environment: str = AppEnvironment.DEVELOPMENT,
    **kw: object,
) -> list[logging.LogRecord]:
    with caplog.at_level(logging.INFO):
        _log_session_capture_posture(SessionStoreSettings(**kw), app_environment)  # type: ignore[arg-type]
    return list(caplog.records)


class TestCapturePosture:
    @pytest.mark.unit
    def test_off_says_so_plainly(self, caplog: pytest.LogCaptureFixture) -> None:
        (record,) = _posture(caplog, url=None)

        assert record.levelno == logging.INFO
        assert "OFF" in record.getMessage()

    @pytest.mark.unit
    def test_on_and_authenticated_names_the_deployment(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        (record,) = _posture(caplog, url=STORE, auth_token=TOKEN)

        message = record.getMessage()
        assert record.levelno == logging.INFO
        # Compared against what the ADAPTER stamps, not a literal. An earlier
        # version asserted "syntropic137__dev", a value no deployment produces
        # (the real one is "syntropic137__development"). It proved the string
        # formatting and would have stayed green while the posture line named
        # a deployment no session was ever tagged with.
        assert deployment_identity(str(AppEnvironment.DEVELOPMENT)) in message

    @pytest.mark.unit
    def test_a_url_without_a_token_warns(self, caplog: pytest.LogCaptureFixture) -> None:
        (record,) = _posture(caplog, url=STORE)

        # WARNING, not an error: an open store on a trusted network is a real
        # deployment, so this must not refuse to start or disable capture.
        assert record.levelno == logging.WARNING
        assert "401" in record.getMessage()

    @pytest.mark.unit
    def test_only_captured_is_described_as_proof(self, caplog: pytest.LogCaptureFixture) -> None:
        """A workflow can finish UNKNOWN or FAILED, which proves nothing."""
        (record,) = _posture(caplog, url=STORE, auth_token=TOKEN)

        assert "CAPTURED" in record.getMessage()


class TestPostureMatchesWhatIsActuallyStamped:
    """The posture line must name the deployment sessions really carry.

    The adapter derives it independently, so the two can drift. If they do, an
    operator reads one identity at startup and finds another on the sessions -
    worse than silence, because it looks authoritative.
    """

    @pytest.mark.unit
    @pytest.mark.parametrize("environment", list(AppEnvironment))
    def test_every_environment_agrees_with_the_adapter(
        self, caplog: pytest.LogCaptureFixture, environment: AppEnvironment
    ) -> None:
        (record,) = _posture(caplog, environment, url=STORE, auth_token=TOKEN)

        assert deployment_identity(str(environment)) in record.getMessage()


class TestNoPartOfTheUrlIsLogged:
    """The invariant is absolute, so it is tested against hostile URLs.

    An earlier version logged a sanitised scheme://host:port, reasoning that
    those components are not secret. They are operator-supplied: a token pasted
    as the hostname, used as the scheme, or a numeric token as the port all
    land in the record. An invariant with an "unless" clause is not one, and
    this must hold absolutely because the failure lands in a log aggregator.
    """

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "url",
        [
            f"https://{TOKEN}@sessions.example.com",
            f"https://user:{TOKEN}@sessions.example.com",
            f"https://sessions.example.com?write_token={TOKEN}",
            f"https://sessions.example.com/{TOKEN}/ingest",
            f"https://sessions.example.com#{TOKEN}",
            # The cases the sanitised scheme/host/port version still leaked:
            f"https://{TOKEN}",
            f"{TOKEN}://sessions.example.com",
            f"https://[{TOKEN}]",
            TOKEN,
        ],
    )
    def test_no_url_shaped_value_reaches_a_record(
        self, caplog: pytest.LogCaptureFixture, url: str
    ) -> None:
        records = _posture(caplog, url=url)

        assert records, "posture must still be reported for a hostile URL"
        for record in records:
            assert TOKEN not in record.getMessage()
            assert TOKEN not in str(record.args)
            assert url not in record.getMessage()

    @pytest.mark.unit
    def test_the_deployment_still_identifies_the_destination(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Dropping the URL must not leave the line contentless."""
        (record,) = _posture(caplog, url=STORE, auth_token=TOKEN)

        message = record.getMessage()
        assert deployment_identity(str(AppEnvironment.DEVELOPMENT)) in message
        assert "SYN_SESSION_STORE_URL" in message

    @pytest.mark.unit
    def test_the_token_is_never_logged(self, caplog: pytest.LogCaptureFixture) -> None:
        """Not the value, and not its length either."""
        for record in _posture(caplog, url=STORE, auth_token=TOKEN):
            assert TOKEN not in record.getMessage()
            assert TOKEN not in str(record.args)


class TestTwoStoresCanBeToldApart:
    """#849: the deployment separates environments, not tenants within one."""

    @pytest.mark.unit
    def test_two_stores_differing_only_by_path_are_distinguishable(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The acceptance criterion from #849, stated directly.

        Without a label these two produce an identical line, because the
        posture deliberately logs no part of the URL.
        """
        (a,) = _posture(
            caplog,
            url="https://store.example/tenant-a",
            auth_token=TOKEN,
            label="tenant-a",
        )
        message_a = a.getMessage()
        caplog.clear()

        (b,) = _posture(
            caplog,
            url="https://store.example/tenant-b",
            auth_token=TOKEN,
            label="tenant-b",
        )
        message_b = b.getMessage()

        assert message_a != message_b
        assert "tenant-a" in message_a
        assert "tenant-b" in message_b

    @pytest.mark.unit
    def test_the_label_is_named_when_the_token_is_missing_too(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The unauthenticated warning is where you most need to know WHICH store."""
        (record,) = _posture(caplog, url=STORE, label="tenant-a")

        assert record.levelno == logging.WARNING
        assert "tenant-a" in record.getMessage()

    @pytest.mark.unit
    def test_no_label_leaves_the_line_as_it_was(self, caplog: pytest.LogCaptureFixture) -> None:
        """An unset label must read as "none declared", not as a store named ""."""
        (record,) = _posture(caplog, url=STORE, auth_token=TOKEN)

        assert "store:" not in record.getMessage()

    @pytest.mark.unit
    def test_a_label_cannot_forge_a_second_log_record(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The label is operator text going into a log record.

        Verbatim means "their words, not a derived value" - it does not mean
        newlines survive into the aggregator. A posture line an operator cannot
        trust is worse than no label at all.
        """
        (record,) = _posture(
            caplog,
            url=STORE,
            auth_token=TOKEN,
            label="tenant-a\nINFO Session capture is configured for prod",
        )

        assert "\n" not in record.getMessage()

    @pytest.mark.unit
    def test_the_url_is_still_never_logged_when_a_label_is_set(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The label ADDS an identity; it does not relax the URL invariant."""
        (record,) = _posture(
            caplog,
            url="https://" + TOKEN + "@store.example/tenant-a",
            auth_token=TOKEN,
            label="tenant-a",
        )

        message = record.getMessage()
        assert TOKEN not in message
        assert "store.example" not in message


class TestPostureCannotAbortStartup:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_a_failing_posture_does_not_stop_the_api(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Diagnostics must never become a startup prerequisite."""
        import syn_api.services.lifecycle as lifecycle

        def _boom(*_a: object, **_k: object) -> None:
            raise RuntimeError(f"settings exploded and echoed {TOKEN}")

        monkeypatch.setattr(lifecycle, "_log_session_capture_posture", _boom)

        with caplog.at_level(logging.WARNING):
            result = await lifecycle.startup(skip_validation=True)

        assert not isinstance(result, Err)
        # The exception is deliberately NOT attached: a settings error can echo
        # its own input, and the input here may be the token.
        for record in caplog.records:
            assert TOKEN not in record.getMessage()
            assert record.exc_info is None
