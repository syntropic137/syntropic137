"""A URL password must never reach a log line, whoever logs the URL."""

from __future__ import annotations

import io
import logging

import pytest

from syn_shared.logging.redaction import install_credential_redaction, redact_url_credentials

pytestmark = pytest.mark.unit

SECRET = "752d61ec9cd57ca11e7e6e6abfaeac14"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (f"redis://:{SECRET}@redis:6379/0", "redis://:***@redis:6379/0"),
        (f"postgresql://syn:{SECRET}@db:5432/x", "postgresql://syn:***@db:5432/x"),
        (
            f"a redis://:{SECRET}@r/0 and amqp://u:{SECRET}@q//",
            "a redis://:***@r/0 and amqp://u:***@q//",
        ),
        ("redis://redis:6379/0", "redis://redis:6379/0"),
        ("https://user@github.com/org/repo", "https://user@github.com/org/repo"),
    ],
)
def test_redacts_only_the_password(raw: str, expected: str) -> None:
    assert redact_url_credentials(raw) == expected


def test_installed_filter_masks_records_from_any_logger() -> None:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    root = logging.getLogger()
    root.addHandler(handler)
    # A logger with its own handler that does not propagate, like uvicorn's.
    isolated = logging.getLogger("test.redaction.isolated")
    isolated_stream = io.StringIO()
    isolated.addHandler(logging.StreamHandler(isolated_stream))
    isolated.propagate = False
    try:
        install_credential_redaction()
        install_credential_redaction()  # idempotent
        logging.getLogger("test.redaction.child").warning(
            "using Redis signal queue (%s)", f"redis://:{SECRET}@redis:6379/0"
        )
        isolated.warning("db %s", f"postgresql://u:{SECRET}@db/x")
    finally:
        root.removeHandler(handler)
        isolated.handlers.clear()

    assert SECRET not in stream.getvalue()
    assert "redis://:***@redis:6379/0" in stream.getvalue()
    assert SECRET not in isolated_stream.getvalue()
    assert len(handler.filters) == 1
