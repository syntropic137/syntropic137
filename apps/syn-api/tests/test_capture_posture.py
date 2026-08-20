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

    # Sentinels chosen so NO url component can be mistaken for the label. An
    # earlier version of these tests used label="tenant-a" against the path
    # /tenant-a, so a posture line that logged the URL PATH looked identical to
    # one that logged the label - and a codex mutation that appended
    # `store.url.rsplit("/")[-1]` to the destination passed the entire suite,
    # including the test named "the url is still never logged".
    # EVERY component gets its own sentinel, including the scheme. A first
    # version used a conventional https URL with only host and path sentinels,
    # and codex pointed out that a label-conditional mutation leaking the query,
    # userinfo, port or fragment would still pass - and that asserting
    # "https://" checks the scheme as a literal rather than as a value.
    URL_COMPONENTS = (
        "url-scheme",
        "url-user",
        "url-password",
        "url-host.example",
        "43127",
        "url-path",
        "url-query",
        "url-fragment",
    )
    URL_WITH_PARTS = (
        "url-scheme://url-user:url-password@url-host.example:43127/url-path?url-query#url-fragment"
    )
    LABEL = "declared-label"

    def _assert_no_url_component(self, record: logging.LogRecord) -> None:
        """No part of the URL, by any route, including the unformatted args."""
        haystacks = (record.getMessage(), str(record.args), str(record.exc_info))
        for haystack in haystacks:
            for component in self.URL_COMPONENTS:
                assert component not in haystack, (
                    f"URL component {component!r} reached a log record"
                )
            assert TOKEN not in haystack

    @pytest.mark.unit
    def test_two_stores_differing_only_by_path_are_distinguishable(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The acceptance criterion from #849, stated directly.

        Labels are unrelated to the paths, so this cannot be satisfied by
        logging the path.
        """
        (a,) = _posture(
            caplog,
            url="https://store.example/tenant-a",
            auth_token=TOKEN,
            label="alpha",
        )
        message_a = a.getMessage()
        caplog.clear()

        (b,) = _posture(
            caplog,
            url="https://store.example/tenant-b",
            auth_token=TOKEN,
            label="bravo",
        )
        message_b = b.getMessage()

        assert message_a != message_b
        assert "alpha" in message_a
        assert "bravo" in message_b
        for message in (message_a, message_b):
            assert "tenant-a" not in message
            assert "tenant-b" not in message

    @pytest.mark.unit
    def test_no_url_component_is_logged_on_the_authenticated_path(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        (record,) = _posture(caplog, url=self.URL_WITH_PARTS, auth_token=TOKEN, label=self.LABEL)

        assert self.LABEL in record.getMessage()
        self._assert_no_url_component(record)

    @pytest.mark.unit
    def test_no_url_component_is_logged_on_the_unauthenticated_path(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The warning branch needs the same guarantee as the healthy one."""
        (record,) = _posture(caplog, url=self.URL_WITH_PARTS, label=self.LABEL)

        assert record.levelno == logging.WARNING
        assert self.LABEL in record.getMessage()
        self._assert_no_url_component(record)

    @pytest.mark.unit
    def test_no_label_leaves_the_line_as_it_was(self, caplog: pytest.LogCaptureFixture) -> None:
        """An unset label must read as "none declared", not a store named ""."""
        (record,) = _posture(caplog, url=STORE, auth_token=TOKEN)

        assert "store:" not in record.getMessage()

    @pytest.mark.unit
    def test_capture_off_names_no_label(self, caplog: pytest.LogCaptureFixture) -> None:
        """With no store there is no destination to identify."""
        (record,) = _posture(caplog, url=None, label=self.LABEL)

        assert self.LABEL not in record.getMessage()

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "unusable",
        [
            "tenant-a\nINFO Session capture is configured for prod",
            "tenant\u2013a",
            "z" * 65,
            "https://url-host-sentinel.example/url-path-sentinel",
            TOKEN + "!",
        ],
        ids=["newline", "homoglyph-dash", "too-long", "a-pasted-url", "a-pasted-token"],
    )
    @pytest.mark.parametrize("authenticated", [True, False], ids=["with-token", "no-token"])
    def test_an_unusable_label_is_ignored_and_never_echoed(
        self, caplog: pytest.LogCaptureFixture, unusable: str, authenticated: bool
    ) -> None:
        """Rejected, and the rejected text is not repeated anywhere.

        Whatever was set is probably not what the operator believed they set,
        so echoing it is how a mis-pasted secret reaches the log this line
        exists to keep clean.
        """
        # Both branches: an earlier version only exercised the authenticated
        # one, so a mutation echoing store.label in the UNAUTHENTICATED warning
        # would have stayed green.
        records = _posture(
            caplog,
            url=STORE,
            auth_token=TOKEN if authenticated else None,
            label=unusable,
        )

        warnings = [r for r in records if r.levelno == logging.WARNING]
        assert warnings, "an unusable label must be reported"

        for record in records:
            haystacks = (record.getMessage(), str(record.args))
            for haystack in haystacks:
                assert unusable not in haystack
                assert "\n" not in haystack


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
