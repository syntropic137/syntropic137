"""An old shipped image or signer identity is named at startup, never overridden (#1398)."""

from __future__ import annotations

import logging

import pytest

from syn_api._wiring import _warn_if_stale_defaults
from syn_shared.settings.image_verification import (
    AGENTIC_PRIMITIVES_IDENTITY_REGEXP,
    PREVIOUS_DEFAULT_IMAGE_IDENTITY_REGEXPS,
    WORKSPACE_IMAGE_IDENTITY_REGEXP,
)
from syn_shared.settings.workspace_images import (
    DEFAULT_WORKSPACE_IMAGE,
    PREVIOUS_DEFAULT_WORKSPACE_IMAGES,
)

pytestmark = pytest.mark.unit

CUSTOM_IMAGE = "ghcr.io/example/custom@sha256:" + "ef" * 32
LOGGER = "syn_api._wiring"


def test_previous_default_image_is_warned(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        _warn_if_stale_defaults(
            PREVIOUS_DEFAULT_WORKSPACE_IMAGES[-1], WORKSPACE_IMAGE_IDENTITY_REGEXP
        )
    assert DEFAULT_WORKSPACE_IMAGE in caplog.text
    assert "SYN_WORKSPACE_DOCKER_IMAGE" in caplog.text
    assert "older release" in caplog.text


@pytest.mark.parametrize("identity", PREVIOUS_DEFAULT_IMAGE_IDENTITY_REGEXPS)
def test_previous_default_identity_is_warned(
    identity: str, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        _warn_if_stale_defaults(DEFAULT_WORKSPACE_IMAGE, identity)
    assert "SYN_IMAGE_VERIFY_CERTIFICATE_IDENTITY_REGEXP" in caplog.text
    assert WORKSPACE_IMAGE_IDENTITY_REGEXP in caplog.text
    assert "older release" in caplog.text


@pytest.mark.parametrize(
    ("image", "identity"),
    [
        (DEFAULT_WORKSPACE_IMAGE, WORKSPACE_IMAGE_IDENTITY_REGEXP),
        (CUSTOM_IMAGE, WORKSPACE_IMAGE_IDENTITY_REGEXP),
        (DEFAULT_WORKSPACE_IMAGE, r"^https://github\.com/example/.*$"),
        # A custom (e.g. AP rollback) image may need a previously shipped identity.
        (CUSTOM_IMAGE, AGENTIC_PRIMITIVES_IDENTITY_REGEXP),
    ],
)
def test_current_or_custom_values_are_quiet(
    image: str, identity: str, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        _warn_if_stale_defaults(image, identity)
    assert caplog.text == ""
