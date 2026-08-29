"""SYN_WORKSPACE_DOCKER_IMAGE: unset uses the pin, blank is an ERROR (#954).

The hot-swap was inert -- the variable never reached the container. The obvious
fix (a `${VAR:-}` passthrough plus a blank-means-default fallback) recreates the
same false pass it was meant to remove:

    SYN_WORKSPACE_DOCKER_IMAGE="$CANDIDATE_IMAGE" docker compose up

With `CANDIDATE_IMAGE` accidentally empty, the operator runs the pinned default
while believing they tested the candidate. Nothing says so.

Compose distinguishes the two states -- a bare `KEY:` resolves to null and is
dropped from the container environment when unset, but an explicitly empty value
is preserved -- so the settings layer distinguishes them too.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from syn_shared.settings.workspace import WorkspaceSettings
from syn_shared.settings.workspace_images import DEFAULT_WORKSPACE_IMAGE

pytestmark = pytest.mark.unit

_VAR = "SYN_WORKSPACE_DOCKER_IMAGE"


def test_unset_uses_the_pinned_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(_VAR, raising=False)
    assert WorkspaceSettings().docker_image == DEFAULT_WORKSPACE_IMAGE


@pytest.mark.parametrize("blank", ["", "   ", "\t"])
def test_explicitly_blank_is_rejected(blank: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """The false-pass guard: a deliberately-set empty value must fail loudly.

    Falling back to the default here is what would let an operator test the
    wrong image and never find out.
    """
    monkeypatch.setenv(_VAR, blank)
    with pytest.raises(ValidationError) as exc:
        WorkspaceSettings()
    message = str(exc.value)
    assert "set but empty" in message
    assert "Unset it" in message, "the error must tell the operator what to do"


def test_a_real_value_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    """The escape hatch must actually work; that is the point of #954."""
    monkeypatch.setenv(_VAR, "ghcr.io/example/other@sha256:deadbeef")
    assert WorkspaceSettings().docker_image == "ghcr.io/example/other@sha256:deadbeef"


def test_the_default_is_a_pinned_digest_not_a_mutable_tag() -> None:
    """A tag would silently change what ran between two identical executions."""
    assert "@sha256:" in DEFAULT_WORKSPACE_IMAGE
