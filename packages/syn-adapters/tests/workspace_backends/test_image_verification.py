"""Image signature verification, with the failure path proven (handoff task 1.4).

A verification step that cannot fail is not a control. The tests that matter
here are the negative ones: an image whose signature does not verify must not
reach the container provider. `TestUnverifiedImageDoesNotRun` proves that end
to end against the real adapter, with a provider double that records whether it
was ever called.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, NoReturn
from unittest.mock import patch

import pytest

from syn_adapters.workspace_backends.errors import WorkspaceProvisionError
from syn_adapters.workspace_backends.image_verification import (
    ImageVerificationError,
    is_remote_reference,
    reset_verification_cache,
    verify_image,
)
from syn_shared.settings.image_verification import (
    AGENTIC_PRIMITIVES_IDENTITY_REGEXP,
    GITHUB_ACTIONS_OIDC_ISSUER,
    ImageVerificationSettings,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from syn_adapters.workspace_backends.agentic.adapter import AgenticIsolationAdapter
    from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
        IsolationConfig,
    )

PINNED_REF = (
    "ghcr.io/agentparadise/agentic-workspace-claude-cli@sha256:"
    "0d53e7a1a9476c5c45cbb7b1467adc004347bef4cf9168c013a6bc7caa5c3f07"
)
LOCAL_REF = "agentic-workspace-claude-cli:dev"


def settings(**overrides: object) -> ImageVerificationSettings:
    """Build settings without reading the developer's .env or environment."""
    defaults: dict[str, object] = {
        "enabled": True,
        "certificate_identity_regexp": AGENTIC_PRIMITIVES_IDENTITY_REGEXP,
        "certificate_oidc_issuer": GITHUB_ACTIONS_OIDC_ISSUER,
        "cosign_path": "cosign",
        "new_bundle_format": True,
        "timeout_seconds": 60.0,
    }
    defaults.update(overrides)
    return ImageVerificationSettings(_env_file=None, **defaults)


@dataclass
class FakeCompleted:
    """Stand-in for subprocess.CompletedProcess."""

    returncode: int
    stdout: str = ""
    stderr: str = ""


@pytest.fixture(autouse=True)
def _clear_cache() -> Iterator[None]:
    """Successful verifications are cached process-wide; isolate each test."""
    reset_verification_cache()
    yield
    reset_verification_cache()


class TestReferenceClassification:
    """The local-versus-remote split decides whether the control applies."""

    @pytest.mark.parametrize(
        "ref",
        [
            "ghcr.io/agentparadise/x@sha256:" + "a" * 64,
            "registry.example.com:5000/x:1",
            "localhost/x:1",
        ],
    )
    def test_remote_references(self, ref: str) -> None:
        assert is_remote_reference(ref) is True

    @pytest.mark.parametrize(
        "ref",
        [
            "agentic-workspace-claude-cli:dev",
            "agentic-workspace-interactive-tmux:latest",
            "myorg/myimage:1",
        ],
    )
    def test_local_references(self, ref: str) -> None:
        assert is_remote_reference(ref) is False


class TestVerificationFailsClosed:
    """Every way verification can go wrong must raise, not warn."""

    def test_bad_signature_raises(self) -> None:
        """cosign exiting non-zero is a hard failure."""
        with (
            patch(
                "syn_adapters.workspace_backends.image_verification.shutil.which",
                return_value="/usr/local/bin/cosign",
            ),
            patch(
                "syn_adapters.workspace_backends.image_verification.subprocess.run",
                return_value=FakeCompleted(1, stderr="no matching signatures"),
            ),
            pytest.raises(ImageVerificationError, match="Signature verification FAILED"),
        ):
            verify_image(PINNED_REF, settings())

    def test_failure_message_carries_cosign_detail(self) -> None:
        """The operator has to be able to tell WHY it failed."""
        with (
            patch(
                "syn_adapters.workspace_backends.image_verification.shutil.which",
                return_value="/usr/local/bin/cosign",
            ),
            patch(
                "syn_adapters.workspace_backends.image_verification.subprocess.run",
                return_value=FakeCompleted(1, stderr="certificate identity mismatch"),
            ),
            pytest.raises(ImageVerificationError) as exc_info,
        ):
            verify_image(PINNED_REF, settings())

        assert "certificate identity mismatch" in str(exc_info.value)

    def test_missing_cosign_raises(self) -> None:
        """cosign absent is a hard failure, not a silent skip.

        A missing verifier and a forged signature have the same outcome if the
        check is skipped, and a missing binary is the most likely way this
        control would quietly stop working.
        """
        with (
            patch(
                "syn_adapters.workspace_backends.image_verification.shutil.which",
                return_value=None,
            ),
            pytest.raises(ImageVerificationError, match="cosign executable"),
        ):
            verify_image(PINNED_REF, settings())

    def test_timeout_raises(self) -> None:
        """A verification that never completes has not verified anything."""
        with (
            patch(
                "syn_adapters.workspace_backends.image_verification.shutil.which",
                return_value="/usr/local/bin/cosign",
            ),
            patch(
                "syn_adapters.workspace_backends.image_verification.subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd="cosign", timeout=60.0),
            ),
            pytest.raises(ImageVerificationError, match="timed out"),
        ):
            verify_image(PINNED_REF, settings())

    def test_remote_tag_reference_rejected(self) -> None:
        """Verifying a tag does not establish what will be pulled."""
        with pytest.raises(ImageVerificationError, match="pinned by tag"):
            verify_image(
                "ghcr.io/agentparadise/agentic-workspace-claude-cli:latest",
                settings(),
            )

    def test_verification_error_is_a_provision_error(self) -> None:
        """Existing error-mapping layers match on WorkspaceProvisionError."""
        assert issubclass(ImageVerificationError, WorkspaceProvisionError)


class TestVerificationSucceeds:
    """The happy path, and what exactly is handed to cosign."""

    def test_valid_signature_passes_and_uses_identity_constraints(self) -> None:
        """Keyless verification is meaningless without identity + issuer flags."""
        with (
            patch(
                "syn_adapters.workspace_backends.image_verification.shutil.which",
                return_value="/usr/local/bin/cosign",
            ),
            patch(
                "syn_adapters.workspace_backends.image_verification.subprocess.run",
                return_value=FakeCompleted(0),
            ) as run,
        ):
            verify_image(PINNED_REF, settings())

        command = run.call_args.args[0]
        assert command[0] == "/usr/local/bin/cosign"
        assert command[1] == "verify"
        assert "--certificate-identity-regexp" in command
        assert "--certificate-oidc-issuer" in command
        identity = command[command.index("--certificate-identity-regexp") + 1]
        issuer = command[command.index("--certificate-oidc-issuer") + 1]
        assert identity == AGENTIC_PRIMITIVES_IDENTITY_REGEXP
        assert issuer == GITHUB_ACTIONS_OIDC_ISSUER
        # The digest, not a tag: this is the reference that will be pulled.
        assert command[-1] == PINNED_REF

    def test_new_bundle_format_flag_is_passed(self) -> None:
        """Without this flag cosign finds no signatures at all, for any image.

        The publisher writes the signature as a Sigstore bundle under the
        'sha256-<digest>' tag, not the legacy 'sha256-<digest>.sig' tag. Drop
        the flag and verification fails 100% of the time, which looks like a
        working control right up until someone disables it to ship.
        """
        with (
            patch(
                "syn_adapters.workspace_backends.image_verification.shutil.which",
                return_value="/usr/local/bin/cosign",
            ),
            patch(
                "syn_adapters.workspace_backends.image_verification.subprocess.run",
                return_value=FakeCompleted(0),
            ) as run,
        ):
            verify_image(PINNED_REF, settings())

        assert "--new-bundle-format" in run.call_args.args[0]

    def test_new_bundle_format_can_be_turned_off(self) -> None:
        """Legacy-signed images need the flag omitted."""
        with (
            patch(
                "syn_adapters.workspace_backends.image_verification.shutil.which",
                return_value="/usr/local/bin/cosign",
            ),
            patch(
                "syn_adapters.workspace_backends.image_verification.subprocess.run",
                return_value=FakeCompleted(0),
            ) as run,
        ):
            verify_image(PINNED_REF, settings(new_bundle_format=False))

        assert "--new-bundle-format" not in run.call_args.args[0]

    def test_success_is_cached_failures_are_not(self) -> None:
        """Digest refs are immutable so caching a pass is safe; a fail may be transient."""
        with (
            patch(
                "syn_adapters.workspace_backends.image_verification.shutil.which",
                return_value="/usr/local/bin/cosign",
            ),
            patch(
                "syn_adapters.workspace_backends.image_verification.subprocess.run",
                return_value=FakeCompleted(0),
            ) as run,
        ):
            verify_image(PINNED_REF, settings())
            verify_image(PINNED_REF, settings())

        assert run.call_count == 1

        reset_verification_cache()
        with (
            patch(
                "syn_adapters.workspace_backends.image_verification.shutil.which",
                return_value="/usr/local/bin/cosign",
            ),
            patch(
                "syn_adapters.workspace_backends.image_verification.subprocess.run",
                return_value=FakeCompleted(1, stderr="boom"),
            ) as run,
        ):
            for _ in range(2):
                with pytest.raises(ImageVerificationError):
                    verify_image(PINNED_REF, settings())

        assert run.call_count == 2

    def test_local_image_is_skipped_so_local_dev_still_works(self) -> None:
        """A locally built image was never published and cannot be signed."""
        with patch("syn_adapters.workspace_backends.image_verification.subprocess.run") as run:
            verify_image(LOCAL_REF, settings())

        run.assert_not_called()

    def test_local_image_skip_is_logged_not_silent(self, caplog: pytest.LogCaptureFixture) -> None:
        """A silent skip is the same defect as no verification."""
        with caplog.at_level("WARNING"):
            verify_image(LOCAL_REF, settings())

        assert any("Skipping signature verification" in r.message for r in caplog.records)

    def test_disabling_is_logged_at_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        """The opt-out must be noisy, so it cannot be forgotten."""
        with caplog.at_level("WARNING"):
            verify_image(PINNED_REF, settings(enabled=False))

        assert any("DISABLED" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# Task 1.4: prove that an image which fails verification does not run.
# ---------------------------------------------------------------------------


@dataclass
class SpyProvider:
    """Records whether the container provider was ever asked to create anything."""

    created: list[object] = field(default_factory=list)

    async def create(self, config: object) -> NoReturn:  # pragma: no cover - must not run
        self.created.append(config)
        msg = "SpyProvider.create was reached; an unverified image would have run"
        raise AssertionError(msg)


class TestUnverifiedImageDoesNotRun:
    """End to end through the real adapter: the container is never created."""

    @staticmethod
    def _adapter_with_spy(image: str) -> tuple[AgenticIsolationAdapter, SpyProvider]:
        from syn_adapters.workspace_backends.agentic.adapter import (
            AgenticIsolationAdapter,
        )

        adapter = AgenticIsolationAdapter(default_image=image)
        spy = SpyProvider()
        adapter._provider = spy  # type: ignore[assignment]  # test double for the provider slot
        return adapter, spy

    @staticmethod
    def _config(image: str = PINNED_REF) -> IsolationConfig:
        # IsolationConfig.image carries its own default, and the adapter
        # prefers config.image over its constructor default, so the image
        # under test has to be set here for it to be the one verified.
        from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
            IsolationConfig,
        )

        return IsolationConfig(
            execution_id="exec-verify-test",
            workspace_id="ws-verify-test",
            image=image,
        )

    @pytest.mark.asyncio
    async def test_bad_signature_prevents_container_creation(self) -> None:
        adapter, spy = self._adapter_with_spy(PINNED_REF)

        with (
            patch(
                "syn_adapters.workspace_backends.image_verification.shutil.which",
                return_value="/usr/local/bin/cosign",
            ),
            patch(
                "syn_adapters.workspace_backends.image_verification.subprocess.run",
                return_value=FakeCompleted(1, stderr="no matching signatures found"),
            ),
            pytest.raises(ImageVerificationError, match="Signature verification FAILED"),
        ):
            await adapter.create(self._config())

        assert spy.created == [], "the provider was called despite a failed verification"

    @pytest.mark.asyncio
    async def test_missing_cosign_prevents_container_creation(self) -> None:
        adapter, spy = self._adapter_with_spy(PINNED_REF)

        with (
            patch(
                "syn_adapters.workspace_backends.image_verification.shutil.which",
                return_value=None,
            ),
            pytest.raises(ImageVerificationError),
        ):
            await adapter.create(self._config())

        assert spy.created == []

    @pytest.mark.asyncio
    async def test_remote_tag_prevents_container_creation(self) -> None:
        tag_ref = "ghcr.io/agentparadise/agentic-workspace-claude-cli:latest"
        adapter, spy = self._adapter_with_spy(tag_ref)

        with pytest.raises(ImageVerificationError, match="pinned by tag"):
            await adapter.create(self._config(tag_ref))

        assert spy.created == []
