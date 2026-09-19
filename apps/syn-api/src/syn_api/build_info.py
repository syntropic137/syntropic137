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

``PackageNotFoundError`` is deliberately not caught. It means ``syn_api`` was
imported without being installed, and there is no honest version to report in
that case; degrading to "unknown" would reintroduce a value that says nothing
while looking like an answer.

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
from importlib.metadata import version

from syn_api.types import BuildInfo

#: The distribution whose installed metadata IS the running release.
PACKAGE_NAME = "syn-api"

#: Stamped by the image build; see module docstring.
ENV_IMAGE_TAG = "SYN_BUILD_IMAGE_TAG"
ENV_COMMIT = "SYN_BUILD_COMMIT"


def get_build_info() -> BuildInfo:
    """Identify the running build.

    Cheap enough to call per request (one metadata read), and uncached on
    purpose: a cached answer would survive a change to the environment it read,
    and this is the one value that must never be stale.
    """
    return BuildInfo(
        version=version(PACKAGE_NAME),
        image_tag=_stamped(ENV_IMAGE_TAG),
        commit=_stamped(ENV_COMMIT),
    )


def _stamped(name: str) -> str | None:
    """Read a build stamp, treating an empty value as absent.

    An unset build arg reaches the container as ``ENV FOO=""``, not as an
    absent variable, so "" and "not stamped" are the same fact and both have to
    report as ``null``.
    """
    return os.environ.get(name) or None
