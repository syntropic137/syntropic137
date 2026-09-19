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

THERE IS NO HONEST VERSION when the distribution is not installed, so none is
produced: ``PackageNotFoundError`` becomes a null release and an explicit
``version_status`` of "unavailable", never a plausible number. Letting it
escape is not the alternative - this is read while FastAPI is being
constructed, so an uncaught raise fails ``create_app()`` and takes down the
service before it can serve the /health that would have explained why.

Deliberately NOT importing syn_api's version of this. The two are separate
distributions reporting their own metadata, so sharing the code would mean a
helper that takes the package name as an argument - the caller supplying the
only fact that matters, which hides nothing. The collector image also carries
no build stamps, so it has no use for the image tag and commit fields.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field

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
    """The running release of this collector, or ``None`` when it is not installed.

    ``PackageNotFoundError`` means ``syn_collector`` was imported without being
    installed - an editable tree, a container that copied the source without
    installing it, a test harness. That is a fact worth reporting accurately
    and is not a reason to refuse to start.
    """
    try:
        return version(PACKAGE_NAME)
    except PackageNotFoundError:
        return None


def version_string() -> str:
    """The running release for the one slot that must hold a non-empty string.

    ``openapi.json``'s ``info.version`` is required by the spec to be one, so
    it cannot spell "unavailable" as the null ``/health`` uses; it says
    ``UNKNOWN_VERSION`` instead. Prefer ``collector_version()`` wherever the
    shape allows a null - it can report the difference, and this cannot.
    """
    return collector_version() or UNKNOWN_VERSION
