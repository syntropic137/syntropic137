"""Metadata the API cannot read must not take the API down (#1380).

``get_build_info()`` reads the running release from ``importlib.metadata``, and
for one revision it let the read's exception escape on the grounds that there is
no honest version to report. There is not — but the two callers make refusing to
answer fatal rather than merely unhelpful: ``syn_api/__init__.py`` reads it
while the package is being imported, and ``create_app()`` reads it again while
FastAPI is being constructed. ``main.py`` builds the global ``app`` at import,
so the process died before it could serve the ``/health`` whose entire job is to
say what is wrong, and it died for a reason no operator would guess from the
traceback.

EVERY TEST HERE IS PARAMETERIZED OVER THE FAILURE, and that is the point of the
file. The revision that fixed this caught ``PackageNotFoundError`` — the one
cause that had been reproduced — and left the class open: a ``PermissionError``
on the dist-info, metadata that will not parse, or anything else distribution
discovery raises still killed the process in precisely the same way. A test
written against a single exception cannot tell a handler for that exception
from a handler for the condition, which is why the narrow fix passed its own
tests. See ``METADATA_FAILURES``.

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

import errno
import importlib
import importlib.metadata
import json
import re
from email.errors import MessageError
from typing import TYPE_CHECKING

import pytest
from httpx import ASGITransport, AsyncClient

import syn_api
from syn_api import build_info
from syn_api.main import create_app

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from pydantic import JsonValue

#: Captured before anything is patched: the release this test run really has
#: installed, and therefore the one string that must NOT surface once the
#: metadata it came from is unreadable.
INSTALLED = importlib.metadata.version(build_info.PACKAGE_NAME)

#: Anything a client could read as a release. Deliberately looser than semver —
#: the point is that no token in these payloads is version-shaped at all.
LOOKS_LIKE_A_RELEASE = re.compile(r"\d+\.\d+\.\d+")

_REAL_VERSION = importlib.metadata.version

#: The ways a metadata read fails, as FACTORIES so each parameter raises a
#: fresh instance rather than one shared object accumulating tracebacks.
#:
#: Not an arbitrary sample. ``PackageNotFoundError`` is the cause that was
#: reproduced and fixed; the other two are the ones that were still fatal
#: afterwards, and they are here because they are the reason this is a class
#: and not an exception. ``PermissionError`` is a real dist-info on a real disk
#: that this process may not read — a root-owned site-packages, a restrictive
#: umask in an image layer. ``MessageError`` is what the stdlib email parser
#: raises on a malformed header, and a wheel's ``METADATA`` file IS an
#: RFC 822 message, so unparseable metadata surfaces exactly there.
#:
#: None of them is ``BaseException``. Adding ``KeyboardInterrupt`` here would
#: be asserting the wrong thing: an interrupt must still stop the process.
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
    """Both readers of syn-api's metadata fail, one parameterized way per run.

    ``build_info`` bound ``version`` by ``from``-import, so that module global
    is what ``get_build_info()`` actually calls; ``importlib.metadata`` itself
    is patched too because the import-time test re-executes module bodies that
    bind a fresh reference from it.
    """
    make_failure: Callable[[str], Exception] = request.param

    def unreadable(name: str) -> str:
        """Narrowed to the one distribution on purpose: a blanket raise would
        also hit every unrelated metadata read FastAPI and httpx make, and the
        test would then be passing for the wrong reason.
        """
        if name == build_info.PACKAGE_NAME:
            raise make_failure(name)
        return _REAL_VERSION(name)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(build_info, "version", unreadable)
        patch.setattr(importlib.metadata, "version", unreadable)
        yield
    # Only now that metadata reads work again: __version__ is evaluated in the
    # module body, so a module left reloaded under the patch would report null
    # to every later test in this process.
    importlib.reload(syn_api)


async def _payload(path: str) -> dict[str, JsonValue]:
    """A response body, parsed from the wire rather than read off the model.

    Every assertion in this file goes through here on purpose. The interesting
    way for this to break is not a wrong value but a right one that never
    reaches a client - dropped at ``BuildInfo``, at the ``info.version``
    argument, or by a serializer - and a test that inspects the model it just
    built cannot see any of those.
    """
    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(path)
    assert response.status_code == 200, response.text
    parsed: dict[str, JsonValue] = json.loads(response.text)
    return parsed


def _release_pair(payload: dict[str, JsonValue]) -> tuple[JsonValue, JsonValue]:
    """The (version, version_status) a response carries, wherever it carries it.

    ``/`` reports the pair flat and ``/health`` reports it inside ``build``.
    That difference is a fact about those two endpoints and not about what is
    being asserted, so it is resolved here once instead of in every test.
    """
    block = payload.get("build", payload)
    assert isinstance(block, dict), payload
    return block.get("version"), block.get("version_status")


@pytest.mark.unit
def test_importing_the_package_survives_an_unreadable_distribution(
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

    Driven through a real request rather than by calling the accessor, because
    the route is the third place the read happens and the only one a client
    ever touches.

    ``version_status`` is what makes the null readable: the other two nulls on
    this block mean "the image did not stamp itself", a different fact, and
    without a named state a client has to guess which absence it is looking at.
    """
    version, status = _release_pair(await _payload("/health"))

    assert version is None
    assert status == "unavailable"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_the_root_endpoint_reports_it_too(metadata_unavailable: None) -> None:
    """The second endpoint that names a release, and it used to lie by sentinel.

    ``/`` served ``"version": "unknown"`` flat, with nothing marking it as a
    stand-in, so a client reading it could not tell an unreadable metadata file
    from a release literally called "unknown" — the same "a literal in a version
    slot" #1380 exists to remove, one endpoint over.
    """
    version, status = _release_pair(await _payload("/"))

    assert version is None
    assert status == "unavailable"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_no_fabricated_release_reaches_a_client(
    metadata_unavailable: None,
) -> None:
    """Nothing version-shaped anywhere a client reads, on every surface.

    The failure this forbids is the tempting one: catching the error and
    returning "0.0.0", or the last known release, or the string the package
    would have had. Every one of those passes a "does it start?" test and
    reintroduces exactly the wrong-but-plausible number #1380 was filed about.

    ``/`` is in the sweep because it was the surface that still carried a bare
    sentinel after the first fix, and a sweep that does not cover every
    response cannot notice the next one.
    """
    rendered = json.dumps(
        [await _payload("/"), await _payload("/health"), create_app().openapi()["info"]]
    )

    assert INSTALLED not in rendered
    assert LOOKS_LIKE_A_RELEASE.search(rendered) is None, rendered


@pytest.mark.unit
@pytest.mark.asyncio
async def test_an_unavailable_response_always_names_its_state(
    metadata_unavailable: None,
) -> None:
    """Every response carrying a version slot also carries a named status.

    The pair is the contract: a null alone is ambiguous (unreadable metadata?
    field not sent? old server?), and a status alone cannot be checked against
    the value it describes. This is the assertion that would have caught the
    root endpoint shipping a sentinel with no status beside it.
    """
    for path in ("/", "/health"):
        version, status = _release_pair(await _payload(path))

        assert version is None, path
        assert status == "unavailable", path


@pytest.mark.unit
@pytest.mark.asyncio
async def test_the_installed_release_is_what_is_reported_when_it_is_readable() -> None:
    """The other half of the contract, unpatched: available means the real value.

    Without this, every assertion above is satisfiable by a build accessor that
    reports "unavailable" unconditionally.
    """
    for path in ("/", "/health"):
        version, status = _release_pair(await _payload(path))

        assert version == INSTALLED, path
        assert status == "installed", path


@pytest.mark.unit
def test_an_interrupt_is_not_swallowed_as_a_missing_release() -> None:
    """``BaseException`` stays fatal: stopping the process is not a null version.

    Catching ``Exception`` and catching everything are one keyword apart, and
    the wider one turns Ctrl-C during startup into a silent "version
    unavailable" and a process that keeps going.
    """

    def interrupted(name: str) -> str:
        raise KeyboardInterrupt

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(build_info, "version", interrupted)
        with pytest.raises(KeyboardInterrupt):
            build_info.get_build_info()
