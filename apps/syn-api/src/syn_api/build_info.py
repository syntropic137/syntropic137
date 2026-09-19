"""Which build is this? One answer, for everything that has to report it.

Three places name the running build — ``openapi.json``'s ``info.version``, the
root endpoint, and (since #1380) ``/health`` — and before this module each
answered separately. The two openapi-facing callers shared a literal
``__version__ = "0.5.1"`` in ``main.py`` that had not moved in twenty-odd
releases, so a VPS running ``syn-api`` ``0.29.1b3`` served ``info.version:
"0.5.1"``: not missing, WRONG, which is worse, because a client that reads it
is misled rather than blocked. ``/health`` said nothing at all, leaving
``docker inspect`` over SSH as the only way to identify a deployment — a check
an agent gating on a rollout cannot make.

THE VERSION IS READ, NEVER WRITTEN HERE. It comes from the installed
distribution's metadata, which is the same string ``pyproject.toml`` ships and
``pip``/``uv`` install. A constant in source would be a second home for the
release number, and a second home drifts the first time someone bumps one and
not the other — which is exactly how "0.5.1" survived into a 0.29.1b3 deploy.
If the number is wrong now, the package really is that version.

THERE IS NO HONEST VERSION when the distribution is not installed, so none is
produced: ``PackageNotFoundError`` becomes a null release and an explicit
``version_status`` of "unavailable", never a plausible number. Inventing one
would be the original defect in a new costume — a value that says nothing while
looking like an answer. Letting the error escape is not the alternative either:
this is read at import time and again while FastAPI is being constructed, so an
uncaught raise takes the whole process down before it can serve the /health
that would have explained why.

THE IMAGE TAG AND COMMIT ARE BUILD-TIME FACTS that no installed artifact
records, so they are stamped into the image as environment variables at build
time (``ARG`` -> ``ENV`` in ``infra/docker/images/syn-api/Dockerfile``) and
read back here. They are absent by default and reported as ``null`` rather
than as a placeholder string, so a caller can tell a build that did not stamp
itself from one that did.

Deliberately NOT ``pydantic-settings`` despite ADR-004. These are not
configuration: nobody should be choosing them per deployment, and putting them
in the generated ``.env.example`` would advertise them as operator-settable —
i.e. would invite hand-editing the answer to "which build is running?", which
is the one question this module exists to answer truthfully.
"""

from __future__ import annotations

import os
from importlib.metadata import PackageNotFoundError, version

from syn_api.types import BuildInfo

#: The distribution whose installed metadata IS the running release.
PACKAGE_NAME = "syn-api"

#: Stamped by the image build; see module docstring.
ENV_IMAGE_TAG = "SYN_BUILD_IMAGE_TAG"
ENV_COMMIT = "SYN_BUILD_COMMIT"

#: What to say where a release has to be a non-empty string and there is none.
#: Not a version number and not shaped like one on purpose: anything downstream
#: that parses or compares ``info.version`` should fail loudly on this rather
#: than quietly accept it as a release that was never built.
UNKNOWN_VERSION = "unknown"


def get_build_info() -> BuildInfo:
    """Identify the running build.

    Cheap enough to call per request (one metadata read), and uncached on
    purpose: a cached answer would survive a change to the environment it read,
    and this is the one value that must never be stale.
    """
    return BuildInfo(
        version=_installed_release(),
        image_tag=_stamped(ENV_IMAGE_TAG),
        commit=_stamped(ENV_COMMIT),
    )


def version_string() -> str:
    """The running release for the slots that must hold a non-empty string.

    ``openapi.json``'s ``info.version`` is required by the spec to be one, and
    the root endpoint publishes a flat map of strings, so neither can spell
    "unavailable" as the null ``/health`` uses; both say ``UNKNOWN_VERSION``
    instead. Prefer ``get_build_info()`` wherever the shape allows it — it can
    report the difference, and this cannot.
    """
    return get_build_info().version or UNKNOWN_VERSION


def _installed_release() -> str | None:
    """The installed release, or ``None`` when there is no distribution to read.

    ``PackageNotFoundError`` means ``syn_api`` was imported without being
    installed — an editable tree, a container that copied the source without
    installing it, a test harness. That is a fact worth reporting accurately
    and is not a reason to refuse to start.
    """
    try:
        return version(PACKAGE_NAME)
    except PackageNotFoundError:
        return None


def _stamped(name: str) -> str | None:
    """Read a build stamp, treating an empty value as absent.

    An unset build arg reaches the container as ``ENV FOO=""``, not as an
    absent variable, so "" and "not stamped" are the same fact and both have to
    report as ``null``.
    """
    return os.environ.get(name) or None
