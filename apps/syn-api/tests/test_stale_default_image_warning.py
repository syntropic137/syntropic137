"""An old shipped default in SYN_WORKSPACE_DOCKER_IMAGE is named at startup, never overridden (#1398)."""

from __future__ import annotations

import logging

import pytest

from syn_api._wiring import _warn_if_stale_default_image
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
