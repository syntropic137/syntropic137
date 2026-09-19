"""Whatever HTTP says the running build is, it must be the installed package (#1380).

The defect this pins was not a missing value, it was a confidently wrong one:
``openapi.json`` reported ``info.version: "0.5.1"`` from a literal in
``main.py`` while the container ran ``syn-api`` ``0.29.1b3``. A test that only
asserted "there is a version field" would have passed against that literal for
every one of the twenty releases it survived, so every assertion here compares
against ``importlib.metadata.version("syn-api")`` — the one value that moves
when the package is bumped and that no hardcoded string can track.

ASSERTED ON THE SERIALIZED PAYLOAD, through the real route and the real
``app.openapi()``, never on ``get_build_info()`` alone. The interesting way to
fail this change is not to compute the version wrongly, it is to compute it
correctly and lose it one hop later — at ``HealthResponse``, which would drop
an undeclared key, or at the ``info.version`` argument, which is passed once at
app construction and is easy to leave pointing at the old constant.
"""

from __future__ import annotations

import json
from importlib.metadata import version

import pytest
from httpx import ASGITransport, AsyncClient

from syn_api.build_info import ENV_COMMIT, ENV_IMAGE_TAG
from syn_api.main import create_app

#: The running release, by the only definition that cannot drift from the
#: package. Not written out here: a literal in this file would be a second
#: place to update and would make the test pass against a stale one.
INSTALLED = version("syn-api")


async def _health_body() -> dict:
    """The /health payload, parsed from the wire rather than from the model."""
    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")
    assert response.status_code == 200, response.text
    return json.loads(response.text)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_health_reports_the_installed_release() -> None:
    """The question an agent gating on a deploy has to be able to ask over HTTP."""
    build = (await _health_body())["build"]

    assert build["version"] == INSTALLED


@pytest.mark.unit
def test_openapi_info_version_is_the_installed_release() -> None:
    """The half that was wrong rather than absent, so the one that misled clients.

    ``info.version`` also feeds the generated CLI types and the docs site, so a
    stale value here propagates into two artifacts nobody re-reads.
    """
    assert create_app().openapi()["info"]["version"] == INSTALLED


@pytest.mark.unit
@pytest.mark.asyncio
async def test_health_and_openapi_cannot_disagree() -> None:
    """Two readings of "which build is this?" that used to have two sources.

    Equal to each other AND to the package: equality alone would still hold if
    both went back to reading one shared constant, which is the arrangement
    that produced the bug.
    """
    body = await _health_body()

    assert body["build"]["version"] == create_app().openapi()["info"]["version"] == INSTALLED


@pytest.mark.unit
@pytest.mark.asyncio
async def test_build_stamps_reach_the_payload_when_the_image_supplies_them(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The image tag and commit survive the model and the serializer.

    Values that could not arise from any default: ``HealthResponse`` defaults
    both to ``None``, so asserting these strings appear proves the stamps were
    carried the whole way rather than that a default was echoed back.
    """
    monkeypatch.setenv(ENV_IMAGE_TAG, "v0.29.1-beta.3")
    monkeypatch.setenv(ENV_COMMIT, "9f3c1ab")

    build = (await _health_body())["build"]

    assert build["image_tag"] == "v0.29.1-beta.3"
    assert build["commit"] == "9f3c1ab"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_an_unstamped_build_says_so_rather_than_guessing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Absent reports as null, and an empty stamp is absent.

    An unset ``ARG`` arrives as ``ENV FOO=""``, so "" is what an unstamped
    image actually holds. Reporting that as an empty string would hand every
    caller a falsy-but-present value to disambiguate; reporting it as
    "unknown" would be a placeholder masquerading as an answer.
    """
    monkeypatch.setenv(ENV_IMAGE_TAG, "")
    monkeypatch.delenv(ENV_COMMIT, raising=False)

    build = (await _health_body())["build"]

    assert build["image_tag"] is None
    assert build["commit"] is None
    # The release is never conditional on the stamps.
    assert build["version"] == INSTALLED


@pytest.mark.unit
def test_the_package_dunder_agrees_with_what_it_serves() -> None:
    """``syn_api.__version__`` was a THIRD spelling of this package's version.

    It read "0.1.0" while ``main.py`` served "0.5.1" and the distribution was
    0.29.x, and ``scripts/import_check.py`` prints it - so a diagnostic whose
    whole job is to confirm what is installed reported a number that had never
    been true. One source or it drifts again.
    """
    import syn_api

    assert syn_api.__version__ == INSTALLED


@pytest.mark.unit
@pytest.mark.asyncio
async def test_the_response_model_does_not_swallow_the_probe_blocks() -> None:
    """Typing /health must not cost it the fields it already reported.

    ``HealthResponse`` declares three fields and allows extras; a model that
    forbade them, or a serializer that dropped them, would silently delete the
    codex and subscription blocks that `syn health` and the deploy runbook
    read. This is the hop the change is most likely to break.
    """
    body = await _health_body()

    assert body["status"] == "healthy"
    assert "codex_auth" in body
    # Absent keys stay absent: the CLI distinguishes "no reasons" from "healthy".
    assert "degraded_reasons" not in body
