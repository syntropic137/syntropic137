"""A URL password must never reach a log line, whoever writes it and whenever.

Runs in a subprocess: installation patches ``logging.Handler.format`` and
replaces ``sys.stdout``/``sys.stderr`` process-wide, which must not leak into
the rest of the test session.
"""

from __future__ import annotations

import re
import subprocess
import sys
import textwrap
from typing import TYPE_CHECKING

import pytest

from syn_shared.logging.redaction import redact_credentials, redact_url_credentials

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit

# Obviously fake. Never paste a real credential into a fixture, even a
# fragment of one: this repo is public.
SECRET = "not-a-real-password-0000000000"


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


# Obviously fake keys in every shape that matters: an underscore in the body is
# the case a `[A-Za-z0-9-]` class cut short, leaving the tail in the log (#1971).
_FAKE_KEYS = (
    "sk-proj-FAKEfakeFAKE0000_tail1111tail2222-end3333",
    "sk-svcacct-FAKE0000fake_1111FAKE-2222",
    "sk-admin-FAKE_0000_fake_1111_2222",
    "sk-ant-oat01-FAKE0000_fake1111-FAKE2222",
    "sk-FAKE0000fake1111FAKE2222fake3333",
)


def _fragments(key: str) -> list[str]:
    """Every piece of ``key`` long enough to identify it, split on its separators."""
    body = key.removeprefix("sk-")
    pieces = [p for p in re.split(r"[-_]", body) if len(p) >= 4]
    return [key, body, *pieces]


@pytest.mark.parametrize("key", _FAKE_KEYS)
@pytest.mark.parametrize(
    "template",
    [
        "stderr: {key}",
        "OPENAI_API_KEY={key}",
        '{{"auth_mode":"apikey","OPENAI_API_KEY":"{key}"}}',
        "ANTHROPIC_API_KEY: {key} trailing",
        "Authorization: Bearer {key}.",
    ],
)
def test_api_keys_are_masked_whole(key: str, template: str) -> None:
    out = redact_credentials(template.format(key=key))
    for fragment in _fragments(key):
        assert fragment not in out, (fragment, out)


def test_a_named_key_without_the_sk_prefix_is_masked() -> None:
    out = redact_credentials('{"OPENAI_API_KEY":"fakeNoPrefix0000_1111"}')
    assert "fakeNoPrefix0000" not in out
    assert "1111" not in out


def test_ordinary_text_is_untouched() -> None:
    text = "task-runner sk-learn OPENAI_API_KEY are set; see https://x.y/p"
    assert redact_credentials(text) == text


def test_an_empty_assignment_does_not_swallow_the_next_line() -> None:
    """``K=`` with no value must not mask the following line (#1972 review)."""
    for text in (
        "OPENAI_API_KEY=\nENOENT:/workspace/repo/package.json\n",
        "OPENAI_API_KEY:\nENOENT:/workspace/repo/package.json\n",
    ):
        assert redact_credentials(text) == text


def test_workspace_redaction_masks_the_whole_key() -> None:
    """The container-side patterns had the same underscore gap (#1971 review)."""
    from syn_shared.settings.workspace_security import ContainerLoggingSettings

    redactor = ContainerLoggingSettings()
    for key in _FAKE_KEYS:
        out = redactor.redact(f"leaked {key} here")
        for fragment in _fragments(key):
            assert fragment not in out, (fragment, out)


_KEY_SCENARIO = textwrap.dedent(
    f"""
    import logging, sys
    from syn_shared.logging.redaction import install_credential_redaction
    install_credential_redaction()
    logging.basicConfig(stream=sys.stderr, format="%(levelname)s %(message)s")
    log = logging.getLogger("setup")
    for key in {_FAKE_KEYS!r}:
        log.error("Secret-injection setup failed: %s", "boom " + key)
        print("print", key)
    """
)


def test_every_output_path_masks_api_keys() -> None:
    done = subprocess.run(
        [sys.executable, "-c", _KEY_SCENARIO],
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    written = done.stdout + done.stderr
    assert written.count("Secret-injection setup failed") == len(_FAKE_KEYS)
    for key in _FAKE_KEYS:
        for fragment in _fragments(key):
            assert fragment not in written, fragment
