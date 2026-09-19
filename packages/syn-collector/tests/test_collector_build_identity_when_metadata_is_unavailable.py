"""A syn-collector that is not installed must still start and still be honest (#1380).

The same defect the API had, on the service deployed beside it:
``collector_version()`` let ``PackageNotFoundError`` escape, and ``create_app()``
reads it while constructing FastAPI, so the collector died on a metadata read
instead of coming up and saying what it could not determine.

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

import importlib
import importlib.metadata
import json
import re
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

import syn_collector
from syn_collector.collector import version as version_module
from syn_collector.collector.service import create_app
from syn_collector.collector.store import InMemoryObservabilityStore

#: Captured before anything is patched: the release really installed here, and
#: therefore the one string that must not surface once its metadata is gone.
INSTALLED = importlib.metadata.version(version_module.PACKAGE_NAME)

#: Anything a client could read as a release.
LOOKS_LIKE_A_RELEASE = re.compile(r"\d+\.\d+\.\d+")

_REAL_VERSION = importlib.metadata.version


def _as_if_not_installed(name: str) -> str:
    """``importlib.metadata.version`` for a collector that was never installed.

    Narrowed to the one distribution: a blanket raise would also hit the
    unrelated metadata reads FastAPI makes, and the test would pass for the
    wrong reason.
    """
    if name == version_module.PACKAGE_NAME:
        raise importlib.metadata.PackageNotFoundError(name)
    return _REAL_VERSION(name)


@pytest.fixture
def metadata_unavailable() -> Iterator[None]:
    """Both readers of syn-collector's metadata see the package as absent."""
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(version_module, "version", _as_if_not_installed)
        patch.setattr(importlib.metadata, "version", _as_if_not_installed)
        yield
    # Only now that metadata reads work again: __version__ is evaluated in the
    # module body, so a module left reloaded under the patch would report null
    # to every later test in this process.
    importlib.reload(syn_collector)


@pytest.mark.unit
def test_importing_the_package_survives_a_missing_distribution(
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
    """Read off the wire, since the way this breaks is losing it at the model."""
    body = TestClient(create_app(store=InMemoryObservabilityStore())).get("/health").json()

    assert body["version"] is None
    assert body["version_status"] == "unavailable"


@pytest.mark.unit
def test_no_fabricated_release_reaches_a_client(metadata_unavailable: None) -> None:
    """Nothing version-shaped on either surface a client reads."""
    app = create_app(store=InMemoryObservabilityStore())
    rendered = json.dumps(TestClient(app).get("/health").json()) + json.dumps(
        app.openapi()["info"]
    )

    assert INSTALLED not in rendered
    assert LOOKS_LIKE_A_RELEASE.search(rendered) is None, rendered
