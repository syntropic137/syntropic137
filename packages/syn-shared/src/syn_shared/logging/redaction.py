"""Mask credentials embedded in URLs before any log line is written.

A connection URL carries its password in the userinfo part
(``redis://:secret@redis:6379/0``), and logging the URL to say which backend
was chosen printed the password to ``docker logs`` and to the rotating JSONL
log file. Fixing the one call site is not enough: the next
``logger.info("%s", url)`` leaks again.

So redaction sits at the two chokepoints every line passes through, not on a
list of handlers that happens to exist at startup:

* ``logging.Handler.format`` - every stdlib handler (console, rotating file,
  uvicorn's, any created later) turns a record into text here, including
  ``extra`` fields and tracebacks the formatter renders.
* ``sys.stdout`` / ``sys.stderr`` - structlog's ``PrintLogger``, ``print`` and
  uncaught tracebacks bypass logging and write straight to these.

Scope: passwords in ``scheme://user:password@`` URLs, and agent API keys
(#1971): any ``sk-`` key (OpenAI ``sk-proj-``/``sk-svcacct-``/``sk-admin-``,
Anthropic ``sk-ant-``) masked WHOLE, including ``_`` and ``-`` in its body, and
the value of a named credential assignment (``OPENAI_API_KEY=...``,
``"OPENAI_API_KEY": "..."``) whatever its shape. Other bare tokens and query
strings are not recognised here.
"""

from __future__ import annotations

import logging
import re
import sys
from typing import TYPE_CHECKING, Final, TextIO

if TYPE_CHECKING:
    from collections.abc import Callable

#: ``scheme://[user]:password@``. The password runs to the last ``@`` before
#: whitespace, so an unencoded ``/`` or ``@``-free reserved character in it is
#: still masked. Over-masking a lookalike is the safe direction.
_URL_USERINFO: Final = re.compile(
    r"(?P<scheme>[a-zA-Z][a-zA-Z0-9+.-]*://)(?P<user>[^:/@\s]*):[^\s]+?@(?=[^\s@]*(?:\s|$))"
)

MASK: Final = "***"

#: An ``sk-`` API key, masked whole. The body class includes ``_`` and ``-``:
#: a class without ``_`` stops at the first underscore of an OpenAI project key
#: and leaves the rest of it in the log (#1971 review). Sixteen characters
#: minimum so ordinary hyphenated words are not masked.
_API_KEY: Final = re.compile(r"(?<![A-Za-z0-9_-])sk-[A-Za-z0-9_-]{16,}")

#: The value assigned to a named agent credential, in env (``K=v``), YAML
#: (``K: v``) or JSON (``"K": "v"``) form. Catches a key with no ``sk-`` prefix,
#: such as the API-key auth.json synthesised for codex echoed back by a script.
_NAMED_CREDENTIAL: Final = re.compile(
    r"(?P<name>(?<![A-Za-z0-9_])(?:OPENAI_API_KEY|ANTHROPIC_API_KEY|CLAUDE_CODE_OAUTH_TOKEN)"
    r"[\"']?\s*[:=]\s*[\"']?)(?!\*\*\*)[^\s\"',}]+"
)

_INSTALLED_ATTR: Final = "_syn_credential_redaction"


def redact_url_credentials(text: str) -> str:
    """Replace the password in every ``scheme://user:password@`` in ``text``."""
    return _URL_USERINFO.sub(rf"\g<scheme>\g<user>:{MASK}@", text)


def redact_credentials(text: str) -> str:
    """Mask URL passwords, ``sk-`` API keys and named credential values in ``text``."""
    text = _NAMED_CREDENTIAL.sub(rf"\g<name>{MASK}", text)
    text = _API_KEY.sub(MASK, text)
    return redact_url_credentials(text)


class RedactingStream:
    """A text stream that masks credentials in everything written to it."""

    def __init__(self, inner: TextIO) -> None:
        self.inner = inner

    def write(self, text: str) -> int:
        self.inner.write(redact_credentials(text))
        return len(text)

    def __getattr__(self, name: str) -> object:
        return getattr(self.inner, name)


def _redacting_format(
    original: Callable[[logging.Handler, logging.LogRecord], str],
) -> Callable[[logging.Handler, logging.LogRecord], str]:
    def format(self: logging.Handler, record: logging.LogRecord) -> str:
        return redact_credentials(original(self, record))

    setattr(format, _INSTALLED_ATTR, True)
    return format


def install_credential_redaction() -> None:
    """Mask URL passwords in every log line this process writes. Idempotent.

    Call as early as possible. Handlers that already hold the original
    stdout/stderr are repointed at the redacting wrappers; everything created
    later picks the wrappers up from ``sys``.
    """
    if not getattr(logging.Handler.format, _INSTALLED_ATTR, False):
        logging.Handler.format = _redacting_format(logging.Handler.format)  # type: ignore[method-assign]

    wrappers: dict[int, RedactingStream] = {}
    for name in ("stdout", "stderr"):
        current = getattr(sys, name)
        if not isinstance(current, RedactingStream):
            current = RedactingStream(current)
            setattr(sys, name, current)
        wrappers[id(current.inner)] = current

    loggers = [logging.getLogger()] + [
        logger
        for logger in logging.Logger.manager.loggerDict.values()
        if isinstance(logger, logging.Logger)
    ]
    for logger in loggers:
        for handler in logger.handlers:
            if isinstance(handler, logging.StreamHandler):
                wrapper = wrappers.get(id(handler.stream))
                if wrapper is not None:
                    handler.setStream(wrapper)
