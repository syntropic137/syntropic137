"""A distribution that is not installed must not take the API down (#1380).

``get_build_info()`` reads the running release from ``importlib.metadata``, and
for one revision it let ``PackageNotFoundError`` escape on the grounds that
there is no honest version to report. There is not — but the two callers make
refusing to answer fatal rather than merely unhelpful: ``syn_api/__init__.py``
reads it while the package is being imported, and ``create_app()`` reads it
again while FastAPI is being constructed. So the process died before it could
serve the ``/health`` whose entire job is to say what is wrong, and it died for
a reason no operator would guess from the traceback.

The fix is not a fallback string. A plausible release is the defect the issue
exists to remove — ``info.version: "0.5.1"`` against a ``0.29.1b3`` deployment
misled every client that read it — so absence is reported AS absence: a null
release plus an explicit ``version_status``. Asserted on the serialized
payload, because the interesting way to break this is to compute the state
correctly and lose it at ``BuildInfo`` or at the ``info.version`` argument.

``unknown`` appears in exactly one place, ``info.version``, because OpenAPI
requires that field to be a non-empty string and null cannot be spelled there.
It is a word and not a number so that nothing downstream can parse it as a
release; ``test_no_fabricated_release_reaches_a_client`` is what holds that.
"""

from __future__ import annotations

import importlib
import importlib.metadata
import json
import re
from typing import TYPE_CHECKING

import pytest
from httpx import ASGITransport, AsyncClient

import syn_api
from syn_api import build_info
from syn_api.main import create_app

if TYPE_CHECKING:
    from collections.abc import Iterator

#: Captured before anything is patched: the release this test run really has
#: installed, and therefore the one string that must NOT surface once the
#: metadata it came from is unreadable.
INSTALLED = importlib.metadata.version(build_info.PACKAGE_NAME)

#: Anything a client could read as a release. Deliberately looser than semver —
#: the point is that no token in these payloads is version-shaped at all.
LOOKS_LIKE_A_RELEASE = re.compile(r"\d+\.\d+\.\d+")

_REAL_VERSION = importlib.metadata.version


def _as_if_not_installed(name: str) -> str:
    """``importlib.metadata.version`` for a syn-api that was never installed.

    Narrowed to the one distribution on purpose: a blanket raise would also hit
    every unrelated metadata read FastAPI and httpx make, and the test would
    then be passing for the wrong reason.
    """
    if name == build_info.PACKAGE_NAME:
        raise importlib.metadata.PackageNotFoundError(name)
    return _REAL_VERSION(name)


@pytest.fixture
def metadata_unavailable() -> Iterator[None]:
    """Both readers of syn-api's metadata see the package as absent.

    ``build_info`` bound ``version`` by ``from``-import, so that module global
    is what ``get_build_info()`` actually calls; ``importlib.metadata`` itself
    is patched too because the import-time test re-executes module bodies that
    bind a fresh reference from it.
    """
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(build_info, "version", _as_if_not_installed)
        patch.setattr(importlib.metadata, "version", _as_if_not_installed)
        yield
    # Only now that metadata reads work again: __version__ is evaluated in the
    # module body, so a module left reloaded under the patch would report null
    # to every later test in this process.
    importlib.reload(syn_api)


async def _health_body() -> dict:
    """The /health payload, parsed from the wire rather than from the model."""
    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")
    assert response.status_code == 200, response.text
    return json.loads(response.text)


@pytest.mark.unit
def test_importing_the_package_survives_a_missing_distribution(
    metadata_unavailable: None,
) -> None:
    """The first of the two fatal reads, exercised by re-running the module body.

    ``import syn_api`` failing is the worst version of this bug: nothing in the
    process gets far enough to report anything, including the test suite.
    """
    reloaded = importlib.reload(syn_api)

    assert reloaded.__version__ is None


@pytest.mark.unit
def test_the_application_still_constructs(metadata_unavailable: None) -> None:
    """The second fatal read. ``create_app()`` must produce an app that serves.

    ``info.version`` is the one slot that cannot say null, so it says a word no
    release could be — not a zero version, which sorts and compares like one.
    """
    app = create_app()

    assert app.openapi()["info"]["version"] == "unknown"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_health_reports_the_unavailable_state_explicitly(
    metadata_unavailable: None,
) -> None:
    """The answer an operator gets instead of a dead process.

    ``version_status`` is what makes the null readable: the other two nulls on
    this block mean "the image did not stamp itself", a different fact, and
    without a named state a client has to guess which absence it is looking at.
    """
    build = (await _health_body())["build"]

    assert build["version"] is None
    assert build["version_status"] == "unavailable"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_no_fabricated_release_reaches_a_client(
    metadata_unavailable: None,
) -> None:
    """Nothing version-shaped anywhere a client reads, on either surface.

    The failure this forbids is the tempting one: catching the error and
    returning "0.0.0", or the last known release, or the string the package
    would have had. Every one of those passes a "does it start?" test and
    reintroduces exactly the wrong-but-plausible number #1380 was filed about.
    """
    rendered = json.dumps(await _health_body()) + json.dumps(create_app().openapi()["info"])

    assert INSTALLED not in rendered
    assert LOOKS_LIKE_A_RELEASE.search(rendered) is None, rendered
