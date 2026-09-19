"""Metadata the collector cannot read must not take the collector down (#1380).

The same defect the API had, on the service deployed beside it:
``collector_version()`` let the metadata read's exception escape, and both
``syn_collector``'s module body and ``create_app()`` call it, so the collector
died on a metadata read instead of coming up and saying what it could not
determine.

EVERY TEST HERE IS PARAMETERIZED OVER THE FAILURE. The revision that fixed this
caught ``PackageNotFoundError`` alone - the cause that had been reproduced - so
a ``PermissionError`` on the dist-info or metadata that will not parse still
killed ``create_app()`` exactly as before, and the narrow handler passed its own
tests because those tests only ever raised the exception it handled. See
``METADATA_FAILURES``; the API's sibling file carries the same list for the same
reason.

Absence is reported AS absence - a null release plus an explicit
``version_status`` - because the alternative that actually tempts you here is a
fallback string, and a plausible-but-wrong release is the original bug: this
service served ``"0.1.0"`` for twenty-odd releases and every client that read
it was misled rather than blocked.

``unknown`` appears only in ``info.version``, which OpenAPI requires to be a
non-empty string. It is a word rather than a number so nothing downstream can
parse it as a release.
"""

from __future__ import annotations

import errno
import importlib
import importlib.metadata
import json
import re
from email.errors import MessageError
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

import syn_collector
from syn_collector.collector import version as version_module
from syn_collector.collector.service import create_app
from syn_collector.collector.store import InMemoryObservabilityStore

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

#: Captured before anything is patched: the release really installed here, and
#: therefore the one string that must not surface once its metadata is gone.
INSTALLED = importlib.metadata.version(version_module.PACKAGE_NAME)

#: Anything a client could read as a release.
LOOKS_LIKE_A_RELEASE = re.compile(r"\d+\.\d+\.\d+")

_REAL_VERSION = importlib.metadata.version

#: The ways a metadata read fails, as factories so each parameter raises a
#: fresh instance. ``PackageNotFoundError`` is the cause that was fixed; the
#: other two are the ones that were still fatal afterwards. ``PermissionError``
#: is a dist-info this process may not read; ``MessageError`` is what the
#: stdlib email parser raises on a malformed header, and a wheel's ``METADATA``
#: is an RFC 822 message, so unparseable metadata surfaces there.
METADATA_FAILURES: list[Callable[[str], Exception]] = [
    lambda name: importlib.metadata.PackageNotFoundError(name),
    lambda name: PermissionError(
        errno.EACCES,
        "Permission denied",
        f"/usr/lib/python3/site-packages/{name}-0.0.0.dist-info/METADATA",
    ),
    lambda name: MessageError(f"malformed METADATA for {name}: missing header separator"),
]

FAILURE_IDS = ["PackageNotFoundError", "PermissionError", "MessageError"]


@pytest.fixture(params=METADATA_FAILURES, ids=FAILURE_IDS)
def metadata_unavailable(request: pytest.FixtureRequest) -> Iterator[None]:
    """Both readers of syn-collector's metadata fail, one way per run."""
    make_failure: Callable[[str], Exception] = request.param

    def unreadable(name: str) -> str:
        """Narrowed to the one distribution: a blanket raise would also hit the
        unrelated metadata reads FastAPI makes, and the test would pass for the
        wrong reason.
        """
        if name == version_module.PACKAGE_NAME:
            raise make_failure(name)
        return _REAL_VERSION(name)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(version_module, "version", unreadable)
        patch.setattr(importlib.metadata, "version", unreadable)
        yield
    # Only now that metadata reads work again: __version__ is evaluated in the
    # module body, so a module left reloaded under the patch would report null
    # to every later test in this process.
    importlib.reload(syn_collector)


@pytest.mark.unit
def test_importing_the_package_survives_an_unreadable_distribution(
    metadata_unavailable: None,
) -> None:
    """``__version__`` now reads through the accessor, so it inherits its safety.

    That is the point of having one source: the unavailable case is handled in
    one place and the dunder cannot grow its own answer to it.
    """
    reloaded = importlib.reload(syn_collector)

    assert reloaded.__version__ is None


@pytest.mark.unit
def test_the_application_still_constructs(metadata_unavailable: None) -> None:
    """The read that was fatal: ``FastAPI(version=...)`` inside ``create_app()``."""
    app = create_app(store=InMemoryObservabilityStore())

    assert app.openapi()["info"]["version"] == "unknown"


@pytest.mark.unit
def test_health_reports_the_unavailable_state_explicitly(
    metadata_unavailable: None,
) -> None:
    """Driven through a real request, since the way this breaks is losing it at
    the model - and the route is the third place the read happens."""
    body = TestClient(create_app(store=InMemoryObservabilityStore())).get("/health").json()

    assert body["version"] is None
    assert body["version_status"] == "unavailable"


@pytest.mark.unit
def test_no_fabricated_release_reaches_a_client(metadata_unavailable: None) -> None:
    """Nothing version-shaped on either surface a client reads."""
    app = create_app(store=InMemoryObservabilityStore())
    rendered = json.dumps(TestClient(app).get("/health").json()) + json.dumps(app.openapi()["info"])

    assert INSTALLED not in rendered
    assert LOOKS_LIKE_A_RELEASE.search(rendered) is None, rendered


@pytest.mark.unit
def test_the_installed_release_is_what_is_reported_when_it_is_readable() -> None:
    """Unpatched: available means the real value, not a permanent "unavailable".

    Without this, every assertion above is satisfiable by an accessor that
    returns ``None`` unconditionally.
    """
    body = TestClient(create_app(store=InMemoryObservabilityStore())).get("/health").json()

    assert body["version"] == INSTALLED
    assert body["version_status"] == "installed"


@pytest.mark.unit
def test_an_interrupt_is_not_swallowed_as_a_missing_release() -> None:
    """``BaseException`` stays fatal: stopping the process is not a null version."""

    def interrupted(name: str) -> str:
        raise KeyboardInterrupt

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(version_module, "version", interrupted)
        with pytest.raises(KeyboardInterrupt):
            version_module.collector_version()
