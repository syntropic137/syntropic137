"""A blank SYN_WORKSPACE_DOCKER_IMAGE must not override the pinned default (#954).

Compose passes optional variables as `${VAR:-}`, which arrives as an EMPTY
STRING, not an absent variable. Pydantic treats that as a present value, so a
naive passthrough would set `docker_image = ""` for every deployment that does
not use the override -- converting an inert escape hatch into a broken one.
"""

from __future__ import annotations

import pytest

from syn_shared.settings.workspace import WorkspaceSettings
from syn_shared.settings.workspace_images import DEFAULT_WORKSPACE_IMAGE

pytestmark = pytest.mark.unit

_VAR = "SYN_WORKSPACE_DOCKER_IMAGE"


def test_unset_uses_the_pinned_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(_VAR, raising=False)
    assert WorkspaceSettings().docker_image == DEFAULT_WORKSPACE_IMAGE


@pytest.mark.parametrize("blank", ["", "   ", "\t"])
def test_blank_falls_back_to_the_pinned_default(
    blank: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """This is the case that would otherwise break provisioning everywhere."""
    monkeypatch.setenv(_VAR, blank)
    assert WorkspaceSettings().docker_image == DEFAULT_WORKSPACE_IMAGE


def test_a_real_value_still_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    """The escape hatch must actually work; that is the point of #954."""
    monkeypatch.setenv(_VAR, "ghcr.io/example/other@sha256:deadbeef")
    assert WorkspaceSettings().docker_image == "ghcr.io/example/other@sha256:deadbeef"


def test_the_default_is_a_pinned_digest_not_a_mutable_tag() -> None:
    """A tag would silently change what ran between two identical executions."""
    assert "@sha256:" in DEFAULT_WORKSPACE_IMAGE
