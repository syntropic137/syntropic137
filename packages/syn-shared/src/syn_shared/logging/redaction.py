"""Mask credentials embedded in URLs before any log record is written.

A connection URL carries its password in the userinfo part
(``redis://:secret@redis:6379/0``, ``postgresql://user:secret@db/x``), and
logging the URL to say which backend was chosen printed the password in plain
text. Fixing the one call site is not enough: the next ``logger.info("%s", url)``
leaks again. So the mask is a handler filter installed once at startup, and it
applies to every record whatever logger or call site produced it.
"""

from __future__ import annotations

import logging
import re
from typing import Final

#: ``scheme://[user][:password]@`` - the userinfo of any URL. The user name is
#: kept (it identifies, it does not authenticate); the password is replaced.
_URL_USERINFO: Final = re.compile(
    r"(?P<scheme>[a-zA-Z][a-zA-Z0-9+.-]*://)(?P<user>[^:/@\s]*):[^@/\s]+@"
)

MASK: Final = "***"


def redact_url_credentials(text: str) -> str:
    """Replace the password in every ``scheme://user:password@`` in ``text``."""
    return _URL_USERINFO.sub(rf"\g<scheme>\g<user>:{MASK}@", text)


class CredentialRedactingFilter(logging.Filter):
    """Rewrites each record's final message with URL passwords masked."""

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        redacted = redact_url_credentials(message)
        if redacted != message:
            record.msg = redacted
            record.args = None
        return True


def install_credential_redaction() -> None:
    """Attach the filter to every handler that exists now.

    Handler filters, not logger filters: a logger's filters do not apply to
    records propagated from its children, a handler's apply to everything it
    writes. Covers the root handlers and loggers that own handlers of their
    own, such as uvicorn's, which do not propagate to root. Call after logging
    is configured. Idempotent.
    """
    loggers = [logging.getLogger()] + [
        logger
        for logger in logging.Logger.manager.loggerDict.values()
        if isinstance(logger, logging.Logger)
    ]
    for logger in loggers:
        for handler in logger.handlers:
            if not any(isinstance(f, CredentialRedactingFilter) for f in handler.filters):
                handler.addFilter(CredentialRedactingFilter())
