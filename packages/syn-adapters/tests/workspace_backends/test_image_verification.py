"""Image signature verification, with the failure path proven (handoff task 1.4).

A verification step that cannot fail is not a control. The tests that matter
here are the negative ones: an image whose signature does not verify must not
reach the container provider. `TestUnverifiedImageDoesNotRun` proves that end
to end against the real adapter, with a provider double that records whether it
was ever called.

The bypass tests matter for the same reason. `TestNoRegistryHostIsNotLocal`
covers the case where the reference merely *looks* local; `TestVerifierIdentity`
covers a verifier that merely *exits* zero; `TestCacheIsKeyedByPolicy` covers a
pass obtained under a weaker policy being reused under a stronger one. Each of
those is a way to reach `docker run` with nothing verified.
"""

from __future__ import annotations

import asyncio
import subprocess
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, NoReturn
from unittest.mock import patch

import pytest

from syn_adapters.workspace_backends.errors import WorkspaceProvisionError
from syn_adapters.workspace_backends.image_verification import (
    ImageVerificationError,
    has_registry_host,
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

MODULE = "syn_adapters.workspace_backends.image_verification"

PINNED_REF = (
    "ghcr.io/agentparadise/agentic-workspace-claude-cli@sha256:"
    "d16a95f5745627b6d154bc7d0c879410b6a2ce61e7cb46118fa3b3bf852f8cb5"
)
LOCAL_REF = "agentic-workspace-claude-cli:dev"
LOCAL_IMAGE_ID = "sha256:" + "b" * 64

COSIGN_PATH = "/usr/local/bin/cosign"
COSIGN_VERSION_JSON = '{"gitVersion": "v3.1.3", "platform": "darwin/arm64"}'


def settings(**overrides: object) -> ImageVerificationSettings:
    """Build settings without reading the developer's .env or environment."""
    defaults: dict[str, object] = {
        "enabled": True,
        "allow_local_images": False,
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


@dataclass
class FakeCosign:
    """A subprocess.run double that answers the version probe and `verify`.

    The verifier is probed with `cosign version` before its exit codes are
    trusted, so every double has to answer that first. Verify invocations are
    recorded separately from probes: the probe result is cached per binary, so
    counting all subprocess calls would not tell us how often cosign actually
    checked a signature.
    """

    verify_result: FakeCompleted | BaseException = field(default_factory=lambda: FakeCompleted(0))
    version_result: FakeCompleted | None = None
    verify_calls: list[list[str]] = field(default_factory=list)

    def __call__(self, command: list[str], **_kwargs: object) -> FakeCompleted:
        if len(command) > 1 and command[1] == "version":
            return self.version_result or FakeCompleted(0, stdout=COSIGN_VERSION_JSON)
        self.verify_calls.append(list(command))
        if isinstance(self.verify_result, BaseException):
            raise self.verify_result
        result = self.verify_result
        assert isinstance(result, FakeCompleted)
        return result


@contextmanager
def fake_cosign(
    verify_result: FakeCompleted | BaseException | None = None,
    *,
    version_result: FakeCompleted | None = None,
    which: str | None = COSIGN_PATH,
) -> Iterator[FakeCosign]:
    """Patch cosign discovery and execution for the duration of the block."""
    fake = FakeCosign(
        verify_result=FakeCompleted(0) if verify_result is None else verify_result,
        version_result=version_result,
    )
    with (
        patch(f"{MODULE}.shutil.which", return_value=which),
        patch(f"{MODULE}.subprocess.run", side_effect=fake),
    ):
        yield fake


@pytest.fixture(autouse=True)
def _clear_cache() -> Iterator[None]:
    """Successful verifications are cached process-wide; isolate each test."""
    reset_verification_cache()
    yield
    reset_verification_cache()


class TestReferenceClassification:
    """`has_registry_host` decides which arm of the policy applies."""

    @pytest.mark.parametrize(
        "ref",
        [
            "ghcr.io/agentparadise/x@sha256:" + "a" * 64,
            "registry.example.com:5000/x:1",
            "localhost/x:1",
        ],
    )
    def test_references_with_a_registry_host(self, ref: str) -> None:
        assert has_registry_host(ref) is True

    @pytest.mark.parametrize(
        "ref",
        [
            "agentic-workspace-claude-cli:dev",
            "agentic-workspace-omni-agent:latest",
            "myorg/myimage:1",
        ],
    )
    def test_references_without_a_registry_host(self, ref: str) -> None:
        """No registry host. That is NOT the same claim as 'this is local'.

        `myorg/myimage:1` is pulled from Docker Hub when it is not already
        present. `TestNoRegistryHostIsNotLocal` covers what the policy does
        with that fact.
        """
        assert has_registry_host(ref) is False


class TestNoRegistryHostIsNotLocal:
    """Reference syntax must never be read as proof that an image is local.

    Docker pulls `myorg/image:latest` and `ubuntu@sha256:...` from Docker Hub
    when they are not already present. Treating them as local because they name
    no registry means an unsigned remote image runs with verification skipped.
    """

    @pytest.mark.parametrize(
        "ref",
        [
            "myorg/image:latest",
            "myorg/image@sha256:" + "c" * 64,
            "ubuntu@sha256:" + "d" * 64,
            "ubuntu:24.04",
            LOCAL_REF,
        ],
    )
    def test_rejected_by_default_rather_than_skipped(self, ref: str) -> None:
        with (
            patch(f"{MODULE}.subprocess.run") as run,
            pytest.raises(ImageVerificationError, match="names no registry"),
        ):
            verify_image(ref, settings())

        run.assert_not_called()

    def test_error_names_the_switch_that_would_permit_it(self) -> None:
        """An operator has to be able to act on the failure."""
        with pytest.raises(ImageVerificationError) as exc_info:
            verify_image("myorg/image:latest", settings())

        assert "SYN_IMAGE_VERIFY_ALLOW_LOCAL_IMAGES=true" in str(exc_info.value)


class TestLocalImagesWhenExplicitlyEnabled:
    """The local-development path: opt in, must already exist, runs by image ID."""

    def test_resolves_to_the_immutable_image_id(self) -> None:
        """Returning the ID is the whole point: nothing can be swapped in later."""
        with (
            patch(f"{MODULE}.shutil.which", return_value="/usr/bin/docker"),
            patch(
                f"{MODULE}.subprocess.run",
                return_value=FakeCompleted(0, stdout=LOCAL_IMAGE_ID + "\n"),
            ) as run,
        ):
            resolved = verify_image(LOCAL_REF, settings(allow_local_images=True))

        assert resolved == LOCAL_IMAGE_ID
        command = run.call_args.args[0]
        assert command[:4] == ["/usr/bin/docker", "image", "inspect", "--format"]
        assert command[-1] == LOCAL_REF

    def test_image_not_present_is_a_failure_not_a_pull(self) -> None:
        """`docker image inspect` never pulls, and neither do we."""
        with (
            patch(f"{MODULE}.shutil.which", return_value="/usr/bin/docker"),
            patch(
                f"{MODULE}.subprocess.run",
                return_value=FakeCompleted(1, stderr="No such image"),
            ),
            pytest.raises(ImageVerificationError, match="not present on this Docker host"),
        ):
            verify_image(LOCAL_REF, settings(allow_local_images=True))

    def test_non_image_id_output_is_rejected(self) -> None:
        with (
            patch(f"{MODULE}.shutil.which", return_value="/usr/bin/docker"),
            patch(f"{MODULE}.subprocess.run", return_value=FakeCompleted(0, stdout="")),
            pytest.raises(ImageVerificationError, match="not a sha256 image ID"),
        ):
            verify_image(LOCAL_REF, settings(allow_local_images=True))

    def test_use_is_logged_at_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        """Running an unverified image, however deliberately, must be noisy."""
        with (
            caplog.at_level("WARNING"),
            patch(f"{MODULE}.shutil.which", return_value="/usr/bin/docker"),
            patch(
                f"{MODULE}.subprocess.run",
                return_value=FakeCompleted(0, stdout=LOCAL_IMAGE_ID),
            ),
        ):
            verify_image(LOCAL_REF, settings(allow_local_images=True))

        assert any("unverified local workspace image" in r.message for r in caplog.records)

    def test_enabling_local_images_does_not_weaken_registry_references(self) -> None:
        """The switch is about images with no registry host, and nothing else."""
        with (
            fake_cosign(FakeCompleted(1, stderr="no matching signatures")),
            pytest.raises(ImageVerificationError, match="Signature verification FAILED"),
        ):
            verify_image(PINNED_REF, settings(allow_local_images=True))


class TestVerifierIdentity:
    """Exit status alone does not establish that the executable was cosign."""

    def test_a_binary_that_only_exits_zero_is_rejected(self) -> None:
        """/usr/bin/true returns 0 for every image and every identity.

        No subprocess patching here on purpose: this runs the real binary, the
        way an operator who set SYN_IMAGE_VERIFY_COSIGN_PATH=/usr/bin/true
        would. Without an identity probe it produces a cached, logged
        "verified" for an image nothing checked.
        """
        with pytest.raises(ImageVerificationError, match="did not identify itself as cosign"):
            verify_image(PINNED_REF, settings(cosign_path="/usr/bin/true"))

    def test_unparseable_version_output_is_rejected(self) -> None:
        with (
            fake_cosign(version_result=FakeCompleted(0, stdout="hello")),
            pytest.raises(ImageVerificationError, match="did not identify itself as cosign"),
        ):
            verify_image(PINNED_REF, settings())

    def test_unsupported_major_version_is_rejected(self) -> None:
        """v1 has no --certificate-identity-regexp, so keyless cannot be constrained."""
        with (
            fake_cosign(version_result=FakeCompleted(0, stdout='{"gitVersion": "v1.13.1"}')),
            pytest.raises(ImageVerificationError, match="at least major version"),
        ):
            verify_image(PINNED_REF, settings())

    def test_current_cosign_major_versions_are_accepted(self) -> None:
        """v2 introduced the flag and v3 (installed here) still carries it."""
        for version in ('{"gitVersion": "v2.4.1"}', '{"gitVersion": "v3.1.3"}'):
            reset_verification_cache()
            with fake_cosign(version_result=FakeCompleted(0, stdout=version)) as fake:
                verify_image(PINNED_REF, settings())
            assert len(fake.verify_calls) == 1

    def test_plain_text_version_output_is_accepted(self) -> None:
        """cosign prints a banner on stderr and the fields on stdout."""
        plain = FakeCompleted(0, stdout="GitVersion:    v3.1.3\n", stderr="  ___ banner ___")
        with fake_cosign(version_result=plain) as fake:
            verify_image(PINNED_REF, settings())

        assert len(fake.verify_calls) == 1

    def test_probe_result_is_cached(self) -> None:
        """The probe is a subprocess exec on a path that runs every provision."""
        with fake_cosign() as fake:
            verify_image(PINNED_REF, settings())
            verify_image(PINNED_REF, settings())

        assert len(fake.verify_calls) == 1


class TestVerificationFailsClosed:
    """Every way verification can go wrong must raise, not warn."""

    def test_bad_signature_raises(self) -> None:
        """cosign exiting non-zero is a hard failure."""
        with (
            fake_cosign(FakeCompleted(1, stderr="no matching signatures")),
            pytest.raises(ImageVerificationError, match="Signature verification FAILED"),
        ):
            verify_image(PINNED_REF, settings())

    def test_failure_message_carries_cosign_detail(self) -> None:
        """The operator has to be able to tell WHY it failed."""
        with (
            fake_cosign(FakeCompleted(1, stderr="certificate identity mismatch")),
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
            patch(f"{MODULE}.shutil.which", return_value=None),
            pytest.raises(ImageVerificationError, match="cosign executable"),
        ):
            verify_image(PINNED_REF, settings())

    def test_timeout_raises(self) -> None:
        """A verification that never completes has not verified anything."""
        with (
            fake_cosign(subprocess.TimeoutExpired(cmd="cosign", timeout=60.0)),
            pytest.raises(ImageVerificationError, match="timed out"),
        ):
            verify_image(PINNED_REF, settings())

    def test_registry_tag_reference_rejected(self) -> None:
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
        with fake_cosign() as fake:
            returned = verify_image(PINNED_REF, settings())

        command = fake.verify_calls[0]
        assert command[0] == COSIGN_PATH
        assert command[1] == "verify"
        assert "--certificate-identity-regexp" in command
        assert "--certificate-oidc-issuer" in command
        identity = command[command.index("--certificate-identity-regexp") + 1]
        issuer = command[command.index("--certificate-oidc-issuer") + 1]
        assert identity == AGENTIC_PRIMITIVES_IDENTITY_REGEXP
        assert issuer == GITHUB_ACTIONS_OIDC_ISSUER
        # The digest, not a tag: this is the reference that will be pulled.
        assert command[-1] == PINNED_REF
        # And the caller runs exactly what was verified.
        assert returned == PINNED_REF

    def test_new_bundle_format_flag_is_passed(self) -> None:
        """Without this flag cosign finds no signatures at all, for any image.

        The publisher writes the signature as a Sigstore bundle under the
        'sha256-<digest>' tag, not the legacy 'sha256-<digest>.sig' tag. Drop
        the flag and verification fails 100% of the time, which looks like a
        working control right up until someone disables it to ship.
        """
        with fake_cosign() as fake:
            verify_image(PINNED_REF, settings())

        assert "--new-bundle-format" in fake.verify_calls[0]

    def test_new_bundle_format_can_be_turned_off(self) -> None:
        """Legacy-signed images need the flag omitted."""
        with fake_cosign() as fake:
            verify_image(PINNED_REF, settings(new_bundle_format=False))

        assert "--new-bundle-format" not in fake.verify_calls[0]

    def test_success_is_cached_failures_are_not(self) -> None:
        """Digest refs are immutable so caching a pass is safe; a fail may be transient."""
        with fake_cosign() as fake:
            verify_image(PINNED_REF, settings())
            verify_image(PINNED_REF, settings())

        assert len(fake.verify_calls) == 1

        reset_verification_cache()
        with fake_cosign(FakeCompleted(1, stderr="boom")) as fake:
            for _ in range(2):
                with pytest.raises(ImageVerificationError):
                    verify_image(PINNED_REF, settings())

        assert len(fake.verify_calls) == 2

    def test_disabling_is_logged_at_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        """The opt-out must be noisy, so it cannot be forgotten."""
        with caplog.at_level("WARNING"):
            returned = verify_image(PINNED_REF, settings(enabled=False))

        assert any("DISABLED" in r.message for r in caplog.records)
        assert returned == PINNED_REF


class TestCacheIsKeyedByPolicy:
    """A pass under a weaker policy must not satisfy a stronger one.

    Keying the cache on the image reference alone means the first policy to
    verify an image decides the answer for every later policy in the process,
    without cosign being consulted again.
    """

    PERMISSIVE = ".*"

    def test_permissive_identity_pass_does_not_satisfy_the_strict_default(self) -> None:
        with fake_cosign() as permissive:
            verify_image(PINNED_REF, settings(certificate_identity_regexp=self.PERMISSIVE))
        assert len(permissive.verify_calls) == 1

        with (
            fake_cosign(FakeCompleted(1, stderr="no matching signatures")) as strict,
            pytest.raises(ImageVerificationError, match="Signature verification FAILED"),
        ):
            verify_image(PINNED_REF, settings())

        assert len(strict.verify_calls) == 1, "the strict policy rode the permissive cache entry"

    def test_a_different_issuer_is_verified_again(self) -> None:
        with fake_cosign() as first:
            verify_image(PINNED_REF, settings(certificate_oidc_issuer="https://evil.example"))
        assert len(first.verify_calls) == 1

        with (
            fake_cosign(FakeCompleted(1, stderr="issuer mismatch")) as second,
            pytest.raises(ImageVerificationError),
        ):
            verify_image(PINNED_REF, settings())

        assert len(second.verify_calls) == 1

    def test_a_different_bundle_format_mode_is_verified_again(self) -> None:
        with fake_cosign() as first:
            verify_image(PINNED_REF, settings(new_bundle_format=False))
        assert len(first.verify_calls) == 1

        with fake_cosign() as second:
            verify_image(PINNED_REF, settings(new_bundle_format=True))

        assert len(second.verify_calls) == 1

    def test_a_different_verifier_binary_is_verified_again(self) -> None:
        """A pass proved by one binary says nothing about another."""
        with fake_cosign(which="/usr/local/bin/cosign") as first:
            verify_image(PINNED_REF, settings(cosign_path="cosign"))
        assert len(first.verify_calls) == 1

        with fake_cosign(which="/opt/vendor/bin/cosign") as second:
            verify_image(PINNED_REF, settings(cosign_path="/opt/vendor/bin/cosign"))

        assert len(second.verify_calls) == 1


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
            fake_cosign(FakeCompleted(1, stderr="no matching signatures found")),
            pytest.raises(ImageVerificationError, match="Signature verification FAILED"),
        ):
            await adapter.create(self._config())

        assert spy.created == [], "the provider was called despite a failed verification"

    @pytest.mark.asyncio
    async def test_missing_cosign_prevents_container_creation(self) -> None:
        adapter, spy = self._adapter_with_spy(PINNED_REF)

        with (
            patch(f"{MODULE}.shutil.which", return_value=None),
            pytest.raises(ImageVerificationError),
        ):
            await adapter.create(self._config())

        assert spy.created == []

    @pytest.mark.asyncio
    async def test_registry_tag_prevents_container_creation(self) -> None:
        tag_ref = "ghcr.io/agentparadise/agentic-workspace-claude-cli:latest"
        adapter, spy = self._adapter_with_spy(tag_ref)

        with pytest.raises(ImageVerificationError, match="pinned by tag"):
            await adapter.create(self._config(tag_ref))

        assert spy.created == []

    @pytest.mark.asyncio
    async def test_docker_hub_short_name_prevents_container_creation(self) -> None:
        """The bypass this suite used to approve: no registry host, so "local"."""
        adapter, spy = self._adapter_with_spy("myorg/image:latest")

        with pytest.raises(ImageVerificationError, match="names no registry"):
            await adapter.create(self._config("myorg/image:latest"))

        assert spy.created == []

    @pytest.mark.asyncio
    async def test_permitted_local_image_runs_by_image_id(self) -> None:
        """Even the opted-in path hands the provider a content address."""
        adapter, _spy = self._adapter_with_spy(LOCAL_REF)
        spy_config: list[object] = []

        async def _record(config: object) -> NoReturn:
            spy_config.append(config)
            msg = "stop after recording"
            raise RuntimeError(msg)

        adapter._provider = type("P", (), {"create": staticmethod(_record)})()  # type: ignore[assignment]

        with (
            patch(f"{MODULE}.shutil.which", return_value="/usr/bin/docker"),
            patch(
                f"{MODULE}.subprocess.run",
                return_value=FakeCompleted(0, stdout=LOCAL_IMAGE_ID),
            ),
            patch(
                f"{MODULE}.ImageVerificationSettings",
                return_value=settings(allow_local_images=True),
            ),
            pytest.raises(WorkspaceProvisionError),
        ):
            await adapter.create(self._config(LOCAL_REF))

        assert spy_config, "the provider was never reached"
        assert spy_config[0].image == LOCAL_IMAGE_ID  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_verification_does_not_block_the_event_loop(self) -> None:
        """cosign is a network round trip; blocking on it stalls the orchestrator.

        `verify_image` shells out to cosign, which contacts the registry and the
        Sigstore transparency log for up to `timeout_seconds`. Called straight
        from `create()` it holds the event loop for that whole window, which in
        an orchestrator running many workspaces means every unrelated execution
        waits behind one cold image check. A ticker coroutine is the canary: if
        the loop is blocked it starves and its count stays near zero even though
        the wall-clock time elapsed.

        Fail-closed is asserted in the same test on purpose. Moving work across
        an executor boundary is exactly where an exception gets swallowed, so
        the verification failure must still come back out of the await.
        """
        adapter, spy = self._adapter_with_spy(PINNED_REF)
        verify_seconds = 0.25
        done = asyncio.Event()

        async def provision() -> BaseException | None:
            try:
                await adapter.create(self._config())
            except BaseException as exc:  # the canary asserts on it
                return exc
            finally:
                done.set()
            return None

        async def tick() -> int:
            """Count loop turns taken WHILE the provision is in flight."""
            ticks = 0
            while not done.is_set():
                await asyncio.sleep(0.01)
                ticks += 1
            return ticks

        def slow_cosign(command: list[str], **_kwargs: object) -> FakeCompleted:
            if len(command) > 1 and command[1] == "version":
                return FakeCompleted(0, stdout=COSIGN_VERSION_JSON)
            time.sleep(verify_seconds)
            return FakeCompleted(1, stderr="no matching signatures")

        with (
            patch(f"{MODULE}.shutil.which", return_value=COSIGN_PATH),
            patch(f"{MODULE}.subprocess.run", side_effect=slow_cosign),
        ):
            outcome, ticks = await asyncio.gather(provision(), tick())

        assert isinstance(outcome, ImageVerificationError), (
            "the failure did not survive the executor boundary"
        )
        assert spy.created == []
        # A blocked loop takes no turns at all during the verification window.
        assert ticks >= 10, f"the event loop was blocked during verification ({ticks} ticks)"
