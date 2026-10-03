"""Which collector build is answering.

The same fix as ``syn_api.build_info``, applied to the sibling service that had
the identical defect (#1380): ``FastAPI(version="0.1.0")`` and a ``/health``
that reported only ``status``. "0.1.0" was not a stale guess, it was wrong -
the installed distribution has been versioned in lockstep with the product
since it was created - and a wrong version served over HTTP misleads every
client that reads it, which is worse than serving none.

READ FROM INSTALLED METADATA, never written here, for the reason the whole
issue exists: a release number with two homes drifts the first time someone
bumps one and not the other. That includes ``syn_collector.__version__``, which
was a hardcoded "0.1.0" sitting beside this accessor and contradicting it; it
now reads through here, so the package has one version source and not two.

THERE IS NO HONEST VERSION when the distribution's metadata cannot be read, so
none is produced: the read becomes a null release and an explicit
``version_status`` of "unavailable", never a plausible number. Letting it
escape is not the alternative - this is read while FastAPI is being
constructed, so an uncaught raise fails ``create_app()`` and takes down the
service before it can serve the /health that would have explained why.

THE FAILURE IS A CLASS, NOT ONE EXCEPTION. A first cut caught only
``PackageNotFoundError``, leaving a ``PermissionError`` on the dist-info,
malformed metadata, and anything else distribution discovery raises to kill
``create_app()`` exactly as before. They are all the same fact to a caller -
the running build cannot be named - so ``collector_version()`` is the single
place the read happens and it treats any ordinary ``Exception`` as
unavailable, logging the cause. ``BaseException`` is deliberately not caught:
``KeyboardInterrupt`` and ``SystemExit`` are the process being told to stop.

Deliberately NOT importing syn_api's version of this. The two are separate
distributions reporting their own metadata, so sharing the code would mean a
helper that takes the package name as an argument - the caller supplying the
only fact that matters, which hides nothing. The collector image also carries
no build stamps, so it has no use for the image tag and commit fields.
"""

from __future__ import annotations

import logging
from importlib.metadata import version
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field

logger = logging.getLogger(__name__)

#: The distribution whose installed metadata IS the running release.
PACKAGE_NAME = "syn-collector"

#: What to say where a release has to be a non-empty string and there is none.
#: Not a version number and not shaped like one on purpose: anything downstream
#: that parses or compares ``info.version`` should fail loudly on this rather
#: than quietly accept it as a release that was never built.
UNKNOWN_VERSION = "unknown"


class CollectorHealth(BaseModel):
    """Payload of the collector's ``GET /health``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: str = Field(description="'healthy' while the collector is accepting batches.")
    version: str | None = Field(
        description="Installed release of the syn-collector distribution, as reported by "
        "importlib.metadata. Identifies the running build exactly, beta suffixes included. "
        "Null when the distribution's metadata cannot be read, because there is no honest "
        "release to report then and a plausible one would mislead; read version_status.",
    )

    @computed_field(
        description="Whether the running release could be read at all. 'installed' means "
        "version names the distribution this process was installed from; 'unavailable' "
        "means importlib.metadata had no such distribution, version is null, and nothing "
        "has been invented to fill it.",
    )
    @property
    def version_status(self) -> Literal["installed", "unavailable"]:
        """Derived, never passed in, so it cannot contradict ``version``."""
        return "unavailable" if self.version is None else "installed"


def collector_version() -> str | None:
    """The running release of this collector, or ``None`` when it cannot be read.

    THE ONLY PLACE THIS PACKAGE READS ITS OWN METADATA, so it is the only place
    that has to know the read can fail. ``syn_collector.__version__`` and
    ``create_app()`` both call it while a module body is executing, and get a
    release or a null - never an exception.

    Every failure is the same answer because it is the same fact: nothing here
    can name the running build. ``PackageNotFoundError`` means the package was
    imported without being installed; a ``PermissionError`` or unparseable
    metadata means it may be installed and is unreadable anyway. The cause goes
    to the log rather than into the response, because a caller has no different
    action to take for one than the other.
    """
    try:
        return version(PACKAGE_NAME)
    except Exception:
        # Never BaseException: KeyboardInterrupt and SystemExit are the process
        # being asked to stop, not a metadata read failing.
        logger.warning(
            "Could not read installed metadata for %s; reporting the running release as "
            "unavailable. /health will carry version_status='unavailable'.",
            PACKAGE_NAME,
            exc_info=True,
        )
        return None


def version_string() -> str:
    """The running release for the one slot that must hold a non-empty string.

    ``openapi.json``'s ``info.version`` is required by the spec to be one, so
    it cannot spell "unavailable" as the null ``/health`` uses; it says
    ``UNKNOWN_VERSION`` instead. Prefer ``collector_version()`` wherever the
    shape allows a null - it can report the difference, and this cannot.
    """
    return collector_version() or UNKNOWN_VERSION
