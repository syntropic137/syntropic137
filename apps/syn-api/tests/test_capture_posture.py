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


class TestOnePostureCannotSuppressTheOther:
    """They used to share one try block.

    A failure in the capture posture silently skipped the concurrency posture -
    and the test below deliberately makes the capture posture raise, so the
    #865 warning would have been missing on exactly the startup someone was
    debugging. Diagnostics must not become each other's prerequisite.
    """

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_a_failing_capture_posture_still_warns_about_concurrency(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        import syn_api.services.lifecycle as lifecycle
        from syn_shared.env_constants import ENV_SYN_POLLING_MAX_CONCURRENT_DISPATCHES
        from syn_shared.settings import get_settings

        def _boom(*_a: object, **_k: object) -> None:
            raise RuntimeError("capture posture exploded")

        monkeypatch.setattr(lifecycle, "_log_session_capture_posture", _boom)
        monkeypatch.setenv(ENV_SYN_POLLING_MAX_CONCURRENT_DISPATCHES, "4")
        get_settings.cache_clear()  # type: ignore[attr-defined]

        try:
            with caplog.at_level(logging.WARNING):
                await lifecycle.startup(skip_validation=True)
        finally:
            get_settings.cache_clear()  # type: ignore[attr-defined]

        concurrency_warnings = [
            r for r in caplog.records if ENV_SYN_POLLING_MAX_CONCURRENT_DISPATCHES in r.getMessage()
        ]
        assert len(concurrency_warnings) == 1, (
            "the concurrency posture must survive a failing capture posture"
        )


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
