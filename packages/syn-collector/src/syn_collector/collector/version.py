"""Which collector build is answering.

The same fix as ``syn_api.build_info``, applied to the sibling service that had
the identical defect (#1380): ``FastAPI(version="0.1.0")`` and a ``/health``
that reported only ``status``. "0.1.0" was not a stale guess, it was wrong -
the installed distribution has been versioned in lockstep with the product
since it was created - and a wrong version served over HTTP misleads every
client that reads it, which is worse than serving none.

READ FROM INSTALLED METADATA, never written here, for the reason the whole
issue exists: a release number with two homes drifts the first time someone
bumps one and not the other.

Deliberately NOT importing syn_api's version of this. The two are separate
distributions reporting their own metadata, so sharing the code would mean a
helper that takes the package name as an argument - the caller supplying the
only fact that matters, which hides nothing. The collector image also carries
no build stamps, so it has no use for the image tag and commit fields.
"""

from __future__ import annotations

from importlib.metadata import version

from pydantic import BaseModel, ConfigDict, Field

#: The distribution whose installed metadata IS the running release.
PACKAGE_NAME = "syn-collector"


class CollectorHealth(BaseModel):
    """Payload of the collector's ``GET /health``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: str = Field(description="'healthy' while the collector is accepting batches.")
    version: str = Field(
        description="Installed release of the syn-collector distribution, as reported by "
        "importlib.metadata. Identifies the running build exactly, beta suffixes included.",
    )


def collector_version() -> str:
    """The running release of this collector."""
    return version(PACKAGE_NAME)
