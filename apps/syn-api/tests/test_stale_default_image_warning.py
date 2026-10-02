"""An old shipped default in SYN_WORKSPACE_DOCKER_IMAGE is named at startup, never overridden (#1398)."""

from __future__ import annotations

import logging

import pytest

from syn_api._wiring import _warn_if_stale_default_identity, _warn_if_stale_default_image
from syn_shared.settings.image_verification import (
    PREVIOUS_DEFAULT_IMAGE_IDENTITY_REGEXPS,
    WORKSPACE_IMAGE_IDENTITY_REGEXP,
)
from syn_shared.settings.workspace_images import (
    DEFAULT_WORKSPACE_IMAGE,
    PREVIOUS_DEFAULT_WORKSPACE_IMAGES,
)

pytestmark = pytest.mark.unit


def test_previous_default_is_warned(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="syn_api._wiring"):
        _warn_if_stale_default_image(PREVIOUS_DEFAULT_WORKSPACE_IMAGES[-1])
    assert DEFAULT_WORKSPACE_IMAGE in caplog.text
    assert "older release" in caplog.text


@pytest.mark.parametrize(
    "image", [DEFAULT_WORKSPACE_IMAGE, "ghcr.io/example/custom@sha256:" + "ef" * 32]
)
def test_current_or_custom_image_is_quiet(image: str, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="syn_api._wiring"):
        _warn_if_stale_default_image(image)
    assert caplog.text == ""


@pytest.mark.parametrize("identity", PREVIOUS_DEFAULT_IMAGE_IDENTITY_REGEXPS)
def test_previous_default_identity_is_warned(
    identity: str, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING, logger="syn_api._wiring"):
        _warn_if_stale_default_identity(identity, DEFAULT_WORKSPACE_IMAGE)
    assert "SYN_IMAGE_VERIFY_CERTIFICATE_IDENTITY_REGEXP" in caplog.text
    assert WORKSPACE_IMAGE_IDENTITY_REGEXP in caplog.text
    assert "older release" in caplog.text


@pytest.mark.parametrize(
    "identity", [WORKSPACE_IMAGE_IDENTITY_REGEXP, r"^https://github\.com/example/.*$"]
)
def test_current_or_custom_identity_is_quiet(
    identity: str, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING, logger="syn_api._wiring"):
        _warn_if_stale_default_identity(identity, DEFAULT_WORKSPACE_IMAGE)
    assert caplog.text == ""


def test_shipped_identity_beside_a_custom_image_is_quiet(caplog: pytest.LogCaptureFixture) -> None:
    """A custom (e.g. AP rollback) image may need a previously shipped identity."""
    with caplog.at_level(logging.WARNING, logger="syn_api._wiring"):
        _warn_if_stale_default_identity(
            PREVIOUS_DEFAULT_IMAGE_IDENTITY_REGEXPS[0], "ghcr.io/example/custom@sha256:" + "ef" * 32
        )
    assert caplog.text == ""
