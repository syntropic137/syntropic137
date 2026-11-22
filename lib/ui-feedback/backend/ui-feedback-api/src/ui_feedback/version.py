"""Which ui-feedback-api build is answering (#1389).

READ FROM INSTALLED METADATA, never written here. The service used to carry
three literal "0.1.0"s (``__version__``, ``FastAPI(version=...)`` and the root
payload) beside the one in ``pyproject.toml``: four homes for one fact, so the
first bump that missed one would have served a wrong version with no error.
``pyproject.toml`` is now the only home; everything that reports a version
reads it through ``service_version()``.

THERE IS NO HONEST VERSION when the metadata cannot be read, so none is
invented: the read returns ``None`` and the string slots say ``UNKNOWN_VERSION``.
Any ordinary ``Exception`` counts as unreadable (not only
``PackageNotFoundError``: a ``PermissionError`` or malformed metadata is the
same fact to a caller), because this runs while the FastAPI app is being
constructed and an escaping raise would stop the service from starting.
``BaseException`` is not caught: that is the process being told to stop.

The same rules as ``syn_collector.collector.version`` (#1380/#1382), kept
separate on purpose: this module is vendored (ADR-016) and runs standalone, so
it cannot import from the platform.
"""

from __future__ import annotations

import logging
from importlib.metadata import version

logger = logging.getLogger(__name__)

#: The distribution whose installed metadata IS the running release.
PACKAGE_NAME = "ui-feedback-api"

#: For slots that must hold a non-empty string. Not shaped like a version on
#: purpose, so anything that parses it fails loudly instead of trusting it.
UNKNOWN_VERSION = "unknown"


def service_version() -> str | None:
    """The installed release of ui-feedback-api, or ``None`` when unreadable."""
    try:
        return version(PACKAGE_NAME)
    except Exception:
        # Never BaseException: KeyboardInterrupt and SystemExit are the process
        # being asked to stop, not a metadata read failing.
        logger.warning(
            "Could not read installed metadata for %s; reporting its version as %r.",
            PACKAGE_NAME,
            UNKNOWN_VERSION,
            exc_info=True,
        )
        return None


def version_string() -> str:
    """The running release, or ``UNKNOWN_VERSION`` where a string is required."""
    return service_version() or UNKNOWN_VERSION
