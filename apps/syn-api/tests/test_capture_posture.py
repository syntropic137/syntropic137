"""Startup must say whether session capture is on, and where it points.

Capture is a per-workspace concern, so before this its posture was only
observable after a workflow ran. An operator who configured a store and never
started a workflow saw nothing - and the most common misconfiguration (URL set,
token missing) fails at finalize with a suppressed diagnostic, so it produced a
failure count with no cause.
"""

from __future__ import annotations

import logging

import pytest

from syn_adapters.workspace_backends.agentic.session_store_env import (
    deployment_identity,
)
from syn_api.services.lifecycle import _log_session_capture_posture
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
        # Compared against what the ADAPTER actually stamps, not against a
        # literal. An earlier version asserted "syntropic137__dev", which is
        # not a value any deployment produces (the real one is
        # "syntropic137__development"): it proved the formatting and would
        # have stayed green while the posture line named a deployment no
        # session was ever tagged with. A confidently wrong posture is worse
        # than no posture.
        assert deployment_identity(str(AppEnvironment.DEVELOPMENT)) in message
        assert STORE in message

    @pytest.mark.unit
    def test_a_url_without_a_token_warns(self, caplog: pytest.LogCaptureFixture) -> None:
        (record,) = _posture(caplog, url=STORE)

        # WARNING, not an error: an open store on a trusted network is a real
        # deployment, so this must not refuse to start or disable capture.
        assert record.levelno == logging.WARNING
        assert "401" in record.getMessage()

    @pytest.mark.unit
    def test_the_token_is_never_logged(self, caplog: pytest.LogCaptureFixture) -> None:
        """Not the value, and not its length either."""
        records = _posture(caplog, url=STORE, auth_token=TOKEN)

        for record in records:
            assert TOKEN not in record.getMessage()
            assert TOKEN not in str(record.args)


class TestPostureMatchesWhatIsActuallyStamped:
    """The posture line must name the deployment sessions really carry.

    The adapter derives it independently, so the two can drift. If they do,
    an operator reads one identity at startup and finds another on the
    sessions - which is worse than silence, because it looks authoritative.
    """

    @pytest.mark.unit
    @pytest.mark.parametrize("environment", list(AppEnvironment))
    def test_every_environment_agrees_with_the_adapter(
        self, caplog: pytest.LogCaptureFixture, environment: AppEnvironment
    ) -> None:
        (record,) = _posture(caplog, environment, url=STORE, auth_token=TOKEN)

        assert deployment_identity(str(environment)) in record.getMessage()
