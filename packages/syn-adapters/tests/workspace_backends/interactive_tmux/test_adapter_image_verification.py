"""The interactive-tmux adapter must never provision an image nobody verified.

This provider takes its image from its own constructor, not from
WorkspaceConfig, and falls back to a built-in default when it is given None.
So a verification check that only runs "if an image was supplied" is not a
check at all: the path that skips it is the path that provisions the built-in
image. These tests pin that shut at the only point where it can be shut, which
is before the provider object exists.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from syn_adapters.workspace_backends.image_verification import (
    ImageVerificationError,
    reset_verification_cache,
)
from syn_adapters.workspace_backends.interactive_tmux import (
    InteractiveTmuxIsolationAdapter,
)
from syn_adapters.workspace_backends.interactive_tmux import adapter as adapter_mod

if TYPE_CHECKING:
    from collections.abc import Iterator

VERIFY_MODULE = "syn_adapters.workspace_backends.image_verification"

PINNED_REF = (
    "ghcr.io/agentparadise/agentic-workspace-interactive-tmux@sha256:"
    "e9f87445e430bddc18d24c4dc0683a2a192e76ea9d7712160d55dcbe6136971a"
)
LOCAL_REF = "agentic-workspace-interactive-tmux:dev"
LOCAL_IMAGE_ID = "sha256:" + "e" * 64
COSIGN_VERSION_JSON = '{"gitVersion": "v3.1.3"}'


@dataclass
class FakeCompleted:
    """Stand-in for subprocess.CompletedProcess."""

    returncode: int
    stdout: str = ""
    stderr: str = ""


@pytest.fixture(autouse=True)
def _clear_cache() -> Iterator[None]:
    reset_verification_cache()
    yield
    reset_verification_cache()


def _fake_provider() -> MagicMock:
    provider_cls = MagicMock()
    provider_cls.return_value.create = AsyncMock()
    return provider_cls


def test_missing_default_image_is_refused_not_defaulted() -> None:
    """Constructing without an image used to hand the choice to the provider."""
    provider_cls = _fake_provider()

    with (
        patch.object(adapter_mod, "_InteractiveTmuxProvider", provider_cls),
        pytest.raises(ImageVerificationError, match="requires an explicit default_image"),
    ):
        InteractiveTmuxIsolationAdapter(default_image=None)  # type: ignore[arg-type]

    # If the provider had been constructed it would have picked its own image.
    provider_cls.assert_not_called()


def test_empty_default_image_is_refused() -> None:
    provider_cls = _fake_provider()

    with (
        patch.object(adapter_mod, "_InteractiveTmuxProvider", provider_cls),
        pytest.raises(ImageVerificationError, match="requires an explicit default_image"),
    ):
        InteractiveTmuxIsolationAdapter(default_image="")

    provider_cls.assert_not_called()


def _config(image: str) -> object:
    from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
        IsolationConfig,
    )

    return IsolationConfig(execution_id="e", workspace_id="w", image=image, environment={})


@pytest.mark.asyncio
async def test_unverifiable_image_never_reaches_the_provider() -> None:
    """A failed signature must stop provisioning before the provider is built."""
    provider_cls = _fake_provider()

    def run(command: list[str], **_kwargs: object) -> FakeCompleted:
        if len(command) > 1 and command[1] == "version":
            return FakeCompleted(0, stdout=COSIGN_VERSION_JSON)
        return FakeCompleted(1, stderr="no matching signatures")

    with (
        patch.object(adapter_mod, "_InteractiveTmuxProvider", provider_cls),
        patch(f"{VERIFY_MODULE}.shutil.which", return_value="/usr/local/bin/cosign"),
        patch(f"{VERIFY_MODULE}.subprocess.run", side_effect=run),
    ):
        adapter = InteractiveTmuxIsolationAdapter(default_image=PINNED_REF)
        with pytest.raises(ImageVerificationError, match="Signature verification FAILED"):
            await adapter.create(_config(PINNED_REF))

    provider_cls.assert_not_called()


@pytest.mark.asyncio
async def test_docker_hub_short_name_is_not_treated_as_local() -> None:
    provider_cls = _fake_provider()

    with patch.object(adapter_mod, "_InteractiveTmuxProvider", provider_cls):
        adapter = InteractiveTmuxIsolationAdapter(default_image="myorg/image:latest")
        with pytest.raises(ImageVerificationError, match="names no registry"):
            await adapter.create(_config("myorg/image:latest"))

    provider_cls.assert_not_called()


@pytest.mark.asyncio
async def test_provider_receives_the_verified_reference() -> None:
    """What the provider runs is the output of the gate, not its input."""
    provider_cls = _fake_provider()

    def run(command: list[str], **_kwargs: object) -> FakeCompleted:
        if len(command) > 1 and command[1] == "version":
            return FakeCompleted(0, stdout=COSIGN_VERSION_JSON)
        return FakeCompleted(0)

    with (
        patch.object(adapter_mod, "_InteractiveTmuxProvider", provider_cls),
        patch(f"{VERIFY_MODULE}.shutil.which", return_value="/usr/local/bin/cosign"),
        patch(f"{VERIFY_MODULE}.subprocess.run", side_effect=run),
    ):
        adapter = InteractiveTmuxIsolationAdapter(default_image=PINNED_REF)
        await adapter.create(_config(PINNED_REF))

    assert provider_cls.call_args.kwargs["default_image"] == PINNED_REF


@pytest.mark.asyncio
async def test_permitted_local_image_reaches_the_provider_as_an_image_id() -> None:
    """Local development still works, and still cannot be swapped underneath."""
    from syn_shared.settings.image_verification import ImageVerificationSettings

    provider_cls = _fake_provider()
    permissive = ImageVerificationSettings(_env_file=None, allow_local_images=True)

    with (
        patch.object(adapter_mod, "_InteractiveTmuxProvider", provider_cls),
        patch(f"{VERIFY_MODULE}.ImageVerificationSettings", return_value=permissive),
        patch(f"{VERIFY_MODULE}.shutil.which", return_value="/usr/bin/docker"),
        patch(
            f"{VERIFY_MODULE}.subprocess.run",
            return_value=FakeCompleted(0, stdout=LOCAL_IMAGE_ID),
        ),
    ):
        adapter = InteractiveTmuxIsolationAdapter(default_image=LOCAL_REF)
        await adapter.create(_config(LOCAL_REF))

    assert provider_cls.call_args.kwargs["default_image"] == LOCAL_IMAGE_ID
    assert adapter._verified_image == LOCAL_IMAGE_ID
