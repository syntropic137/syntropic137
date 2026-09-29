"""A URL password must never reach a log line, whoever writes it and whenever.

Runs in a subprocess: installation patches ``logging.Handler.format`` and
replaces ``sys.stdout``/``sys.stderr`` process-wide, which must not leak into
the rest of the test session.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from typing import TYPE_CHECKING

import pytest

from syn_shared.logging.redaction import redact_url_credentials

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit

SECRET = "752d61ec9cd57ca11e7e6e6abfaeac14"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (f"redis://:{SECRET}@redis:6379/0", "redis://:***@redis:6379/0"),
        (f"postgresql://syn:{SECRET}@db:5432/x", "postgresql://syn:***@db:5432/x"),
        (f"redis://u:part/{SECRET}@host:6379", "redis://u:***@host:6379"),
        (
            f"a redis://:{SECRET}@r/0 and amqp://u:{SECRET}@q//",
            "a redis://:***@r/0 and amqp://u:***@q//",
        ),
        (f'{{"url": "redis://:{SECRET}@r/0"}}', '{"url": "redis://:***@r/0"}'),
        ("redis://redis:6379/0", "redis://redis:6379/0"),
        ("https://user@github.com/org/repo", "https://user@github.com/org/repo"),
        (
            "see https://github.com/o/r and http://x:8080/p",
            "see https://github.com/o/r and http://x:8080/p",
        ),
    ],
)
def test_redacts_only_the_password(raw: str, expected: str) -> None:
    assert redact_url_credentials(raw) == expected


_SCENARIO = textwrap.dedent(
    f"""
    import logging, logging.config, sys, structlog
    from logging.handlers import RotatingFileHandler

    url = "redis://:{SECRET}@redis:6379/0"

    # A handler that exists BEFORE install, holding the original stderr
    # (uvicorn configures its loggers before importing the app).
    early = logging.getLogger("uvicorn.error")
    early.addHandler(logging.StreamHandler(sys.stderr))
    early.propagate = False

    from syn_shared.logging.redaction import install_credential_redaction
    install_credential_redaction()
    install_credential_redaction()  # idempotent

    # Handlers created AFTER install, including a dictConfig replacement and
    # a rotating file with a JSON-ish formatter that renders `extra`.
    logging.config.dictConfig({{
        "version": 1, "disable_existing_loggers": False,
        "handlers": {{"h": {{"class": "logging.StreamHandler", "stream": "ext://sys.stderr"}}}},
        "loggers": {{"uvicorn.access": {{"handlers": ["h"], "propagate": False}}}},
    }})
    fh = RotatingFileHandler(sys.argv[1])
    fh.setFormatter(logging.Formatter("%(message)s %(source_url)s"))
    logging.getLogger("filelog").addHandler(fh)

    early.warning("early %s", url)
    logging.getLogger("uvicorn.access").warning("late %s", url)
    logging.getLogger("filelog").warning("extra", extra={{"source_url": url}})
    try:
        raise RuntimeError(url)
    except RuntimeError:
        logging.getLogger("uvicorn.access").exception("boom")
    structlog.configure(logger_factory=structlog.PrintLoggerFactory(file=sys.stderr))
    structlog.get_logger().info("structlog", url=url)
    print("print", url)
    fh.close()
    """
)


def test_every_output_path_is_masked(tmp_path: Path) -> None:
    log_file = tmp_path / "agentic.jsonl"
    done = subprocess.run(
        [sys.executable, "-c", _SCENARIO, str(log_file)],
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    written = done.stdout + done.stderr + log_file.read_text()

    assert SECRET not in written
    for marker in ("early", "late", "extra", "boom", "structlog", "print"):
        assert marker in written, marker
    assert written.count("redis://:***@redis:6379/0") >= 6
