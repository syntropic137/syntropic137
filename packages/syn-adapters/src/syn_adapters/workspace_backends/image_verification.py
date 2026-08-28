"""Verify workspace image signatures with cosign before a container is created.

agentic-primitives signs every published workspace image with cosign keyless
OIDC. This module is the consumer half of that: it runs ``cosign verify``
against the exact digest that is about to be run, with the publisher's identity
constraints, and raises if verification does not succeed.

Policy
------
``verify_image`` returns the reference the caller must actually run, which is
not always the reference it was given. Callers must use the return value.
It blocks on a subprocess, so async callers use ``verify_image_async``,
which runs the same policy on a worker thread.

1. **Reference with a registry host, pinned by digest**
   (``ghcr.io/...@sha256:...``) Verified with cosign. Any failure - bad
   signature, wrong signer, no signature, cosign missing, cosign not actually
   being cosign, cosign timing out - raises ``ImageVerificationError`` and the
   container is not created. Returned unchanged.

2. **Reference with a registry host, pinned by tag** (``ghcr.io/...:latest``)
   Rejected. Verifying a tag does not establish what will be pulled: the tag
   can move between the verify call and the pull, and cosign would be attesting
   to a digest that is not necessarily the one Docker resolves. Pin the digest.

3. **Reference with no registry host** (``agentic-workspace-claude-cli:dev``,
   ``myorg/image:latest``, ``ubuntu@sha256:...``)
   Rejected unless local images are explicitly enabled by configuration.

Why case 3 is not simply "local, so skip"
-----------------------------------------
A reference without a registry host is NOT evidence that the image is local.
Docker treats such a reference as a Docker Hub short name and pulls it when it
is not already present: ``myorg/image:latest`` and ``ubuntu@sha256:...`` are
remote, unsigned-as-far-as-we-know images that would have executed unverified
if syntax alone decided the question.

So the question the code asks is not "does this look local" but "has the
operator turned local images on". When
``SYN_IMAGE_VERIFY_ALLOW_LOCAL_IMAGES=true``, the reference must already be
present on the Docker host: it is resolved to that image's immutable local
image ID (``sha256:<64 hex>``), and it is the ID that is returned and run.
That closes the gap between the check and the run - Docker cannot pull it, and
a concurrent ``docker tag`` cannot repoint it, because an image ID is the
content address of the image itself. If the image is not present, provisioning
fails; it never pulls.

Missing cosign is a hard failure, not a warned skip
---------------------------------------------------
``cosign`` not being installed produces the same outcome as a forged signature
would if we skipped: an unverified image runs. A warning in a log nobody is
reading is not a control, and "the tool was missing" is the single most likely
way this check would silently stop working. So it fails closed.

The same reasoning applies to what ``cosign_path`` resolves to. A binary that
exits zero regardless of its arguments (``/usr/bin/true`` is the obvious one,
but any earlier ``cosign`` on PATH will do) would otherwise produce a cached,
logged "verified" for an image nobody checked. Exit status alone does not
establish that the executable was cosign, so the resolved binary is probed with
``cosign version`` and must report a cosign version of at least major
``MINIMUM_COSIGN_MAJOR`` before its exit codes are trusted.

The cost of that strictness is bounded and deliberate:

- Local development still works, through the explicit
  ``SYN_IMAGE_VERIFY_ALLOW_LOCAL_IMAGES`` switch described above, which needs
  no cosign at all.
- An operator who genuinely cannot install cosign has one explicit, recorded
  switch, ``SYN_IMAGE_VERIFY_ENABLED=false``, which logs a WARNING on every
  provision. That is a decision someone makes on purpose, not a control that
  evaporates because a binary is absent from a base image.

Caching
-------
Verification is a network round trip to the registry and the Sigstore
transparency log, and the same image is provisioned many times, so successes
are cached for the process lifetime. The cache key is the whole security
policy, not just the image reference: a reference verified under a permissive
identity regexp, a different issuer, a different bundle-format mode or a
different verifier binary must not be accepted under stricter settings without
cosign running again.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import shutil
import subprocess
import threading
from dataclasses import dataclass

from syn_adapters.workspace_backends.errors import WorkspaceProvisionError
from syn_shared.env_constants import (
    ENV_SYN_IMAGE_VERIFY_ALLOW_LOCAL_IMAGES,
    ENV_SYN_IMAGE_VERIFY_COSIGN_PATH,
    ENV_SYN_IMAGE_VERIFY_ENABLED,
)
from syn_shared.settings.image_verification import (
    MINIMUM_COSIGN_MAJOR,
    ImageVerificationSettings,
)

logger = logging.getLogger(__name__)

__all__ = [
    "ImageVerificationError",
    "has_registry_host",
    "reset_verification_cache",
    "verify_image",
    "verify_image_async",
]


class ImageVerificationError(WorkspaceProvisionError):
    """Raised when a workspace image fails signature verification.

    Subclasses ``WorkspaceProvisionError`` so the existing error-mapping layers
    (``_fail_execution``, ``syn execution show``) surface it with execution
    context, while callers that care specifically about a supply-chain failure
    can still match the narrower type.
    """


#: An immutable local Docker image ID, as reported by ``docker image inspect``.
_IMAGE_ID_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")

#: ``GitVersion:    v3.1.3`` in the human-readable ``cosign version`` output,
#: used only when the machine-readable ``--json`` form is unavailable.
_COSIGN_VERSION_PATTERN = re.compile(r"GitVersion:\s*v?(\d+)\.(\d+)")

#: Timeout for the ``cosign version`` probe. It is a local exec with no network
#: involvement, so it does not need the verification timeout.
_VERSION_PROBE_TIMEOUT_SECONDS = 15.0


@dataclass(frozen=True)
class _Verifier:
    """A cosign executable that has proved it is cosign."""

    path: str
    version: str


# Successful verifications, keyed by the full security policy (see the module
# docstring). Failures are deliberately NOT cached: a failure can be transient
# (network, timeout) and caching it would turn a blip into a sticky outage.
_verified_policies: set[tuple[object, ...]] = set()
# Probed verifier binaries, keyed by the configured cosign path. The probe is a
# subprocess exec on every provision otherwise, and its result is part of the
# verification cache key, so a changed binary cannot ride an old entry.
_verifiers: dict[str, _Verifier] = {}
_cache_lock = threading.Lock()


def reset_verification_cache() -> None:
    """Clear the successful-verification and verifier-probe caches. For tests."""
    with _cache_lock:
        _verified_policies.clear()
        _verifiers.clear()


def has_registry_host(image_ref: str) -> bool:
    """Return True if the reference names a registry host.

    Uses the standard OCI rule: a reference has a registry host only if it
    contains a '/' AND its first component contains a '.' or a ':' (a port), or
    is exactly 'localhost'.

    This answers exactly one question, and it is NOT "is this image local".
    ``myorg/image:latest`` and ``ubuntu@sha256:...`` have no registry host and
    are pulled from Docker Hub all the same. What this decides is whether the
    reference must be digest-pinned and cosign-verified (it names a registry)
    or whether it falls under the explicit local-images switch (it does not).
    """
    head, separator, _ = image_ref.partition("/")
    if not separator:
        return False
    return "." in head or ":" in head or head == "localhost"


def _split_digest(image_ref: str) -> str | None:
    """Return the ``sha256:...`` digest of a reference, or None if tag-based."""
    _, separator, digest = image_ref.rpartition("@")
    if not separator or not digest.startswith("sha256:"):
        return None
    return digest


def _resolve_local_image_id(image_ref: str) -> str:
    """Return the immutable image ID of an image that is already present locally.

    ``docker image inspect`` never pulls, so a reference that is not present
    raises here instead of being fetched from Docker Hub. Returning the ID
    rather than the reference is what makes the check meaningful: the caller
    runs the content address, so nothing can be pulled or retagged underneath
    it between this call and ``docker run``.
    """
    docker = shutil.which("docker")
    if docker is None:
        msg = f"Cannot resolve local workspace image {image_ref!r}: docker was not found on PATH."
        raise ImageVerificationError(msg)

    try:
        completed = subprocess.run(
            [docker, "image", "inspect", "--format", "{{.Id}}", image_ref],
            capture_output=True,
            text=True,
            timeout=_VERSION_PROBE_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        msg = f"Resolving local workspace image {image_ref!r} timed out."
        raise ImageVerificationError(msg) from exc
    except OSError as exc:
        msg = f"Could not execute docker at {docker!r} to resolve {image_ref!r}: {exc}"
        raise ImageVerificationError(msg) from exc

    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        msg = (
            f"Workspace image {image_ref!r} is not present on this Docker host. "
            f"{ENV_SYN_IMAGE_VERIFY_ALLOW_LOCAL_IMAGES}=true permits running an "
            "image that is already built locally; it does not permit pulling "
            "one, because a reference with no registry host is pulled from "
            "Docker Hub and would run unverified. Build the image first, or "
            "point at a digest-pinned registry reference. docker said: "
            f"{detail}"
        )
        raise ImageVerificationError(msg)

    image_id = completed.stdout.strip()
    if not _IMAGE_ID_PATTERN.match(image_id):
        msg = (
            f"Could not read an image ID for {image_ref!r}: docker reported "
            f"{image_id!r}, which is not a sha256 image ID. Refusing to run an "
            "image that cannot be pinned to its content."
        )
        raise ImageVerificationError(msg)

    return image_id


def _run_version_probe(path: str, *json_flag: str) -> subprocess.CompletedProcess[str]:
    """Run ``<path> version [--json]``, raising if it cannot be executed."""
    try:
        return subprocess.run(
            [path, "version", *json_flag],
            capture_output=True,
            text=True,
            timeout=_VERSION_PROBE_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        msg = f"Probing the verifier at {path!r} with 'version' timed out."
        raise ImageVerificationError(msg) from exc
    except OSError as exc:
        msg = f"Could not execute the verifier at {path!r}: {exc}"
        raise ImageVerificationError(msg) from exc


def _gitversion_from_json(completed: subprocess.CompletedProcess[str]) -> str | None:
    """Read ``gitVersion`` out of ``cosign version --json`` output."""
    if completed.returncode != 0:
        return None
    try:
        payload = json.loads(completed.stdout)
    except ValueError:
        return None
    if not isinstance(payload, dict):
        return None
    candidate = payload.get("gitVersion")
    return candidate if isinstance(candidate, str) else None


def _gitversion_from_text(
    path: str,
    completed: subprocess.CompletedProcess[str],
) -> str | None:
    """Read the GitVersion line out of the human-readable ``cosign version``.

    Checked over both streams, because cosign prints its banner on stderr and
    the fields on stdout. Falls back to re-running without ``--json`` in case
    that flag was what the binary rejected.
    """
    match = _COSIGN_VERSION_PATTERN.search(f"{completed.stdout}\n{completed.stderr}")
    if match is None:
        plain = _run_version_probe(path)
        match = _COSIGN_VERSION_PATTERN.search(f"{plain.stdout}\n{plain.stderr}")
    if match is None:
        return None
    return f"v{match.group(1)}.{match.group(2)}"


def _probe_cosign_major(path: str) -> tuple[int, str]:
    """Run ``cosign version`` on ``path`` and return (major, reported version).

    Raises ImageVerificationError if the binary does not identify itself as
    cosign. cosign v2 and v3 both support ``version --json``; the plain-text
    output is parsed as a fallback so a future output change degrades to a
    clear error rather than a false rejection of a genuine cosign.
    """
    completed = _run_version_probe(path, "--json")
    reported = _gitversion_from_json(completed) or _gitversion_from_text(path, completed)
    if reported is None:
        msg = (
            f"The verifier at {path!r} did not identify itself as cosign. "
            "'cosign version' must report a GitVersion; a binary that only "
            "exits zero (for example /usr/bin/true, or an unrelated 'cosign' "
            "earlier on PATH) would make every image verify successfully "
            "without anything being checked. Install cosign "
            "(https://docs.sigstore.dev/cosign/installation/) and point "
            f"{ENV_SYN_IMAGE_VERIFY_COSIGN_PATH} at it."
        )
        raise ImageVerificationError(msg)

    match = re.match(r"^v?(\d+)\.", reported)
    if match is None:
        msg = (
            f"The verifier at {path!r} reported version {reported!r}, which is "
            "not a cosign version. Refusing to trust its exit codes."
        )
        raise ImageVerificationError(msg)
    return int(match.group(1)), reported


def _resolve_verifier(settings: ImageVerificationSettings) -> _Verifier:
    """Locate cosign and prove it is cosign, or raise.

    The result is cached per configured path, because this costs a subprocess
    exec on a code path that runs on every provision.
    """
    with _cache_lock:
        cached = _verifiers.get(settings.cosign_path)
    if cached is not None:
        return cached

    path = shutil.which(settings.cosign_path) or (
        settings.cosign_path if "/" in settings.cosign_path else None
    )
    if path is None:
        msg = (
            f"Cannot verify workspace image: cosign executable "
            f"{settings.cosign_path!r} was not found on PATH. Signature "
            "verification fails closed, because a missing verifier and a "
            "forged signature have the same outcome if the check is skipped. "
            "Install cosign (https://docs.sigstore.dev/cosign/installation/), "
            f"or set {ENV_SYN_IMAGE_VERIFY_ENABLED}=false to accept unverified "
            "images deliberately."
        )
        raise ImageVerificationError(msg)

    major, reported = _probe_cosign_major(path)
    if major < MINIMUM_COSIGN_MAJOR:
        msg = (
            f"The verifier at {path!r} reports cosign {reported}, but at least "
            f"major version {MINIMUM_COSIGN_MAJOR} is required: "
            "--certificate-identity-regexp does not exist before v2, so keyless "
            "verification cannot be constrained to the expected signer."
        )
        raise ImageVerificationError(msg)

    verifier = _Verifier(path=path, version=reported)
    with _cache_lock:
        _verifiers[settings.cosign_path] = verifier
    return verifier


def _policy_key(
    image_ref: str,
    settings: ImageVerificationSettings,
    verifier: _Verifier,
) -> tuple[object, ...]:
    """Build the cache key: the image plus every security-relevant input.

    Anything that changes what "verified" means belongs here. Keying on the
    image reference alone would let a pass obtained under a permissive identity
    regexp, a different issuer, a different bundle-format mode or a different
    cosign binary satisfy a stricter policy without cosign being run again.
    """
    return (
        image_ref,
        settings.certificate_identity_regexp,
        settings.certificate_oidc_issuer,
        settings.new_bundle_format,
        verifier.path,
        verifier.version,
    )


def _resolve_local_reference(
    image_ref: str,
    settings: ImageVerificationSettings,
) -> str:
    """Handle a reference with no registry host, returning what should run."""
    if not settings.allow_local_images:
        msg = (
            f"Workspace image {image_ref!r} names no registry, so its "
            "signature cannot be verified. This is NOT treated as a local "
            "image: Docker pulls a reference like this from Docker Hub when "
            "it is not already present, so accepting it on syntax alone "
            "would run an unverified remote image. Use a digest-pinned "
            "registry reference (registry/name@sha256:...), or set "
            f"{ENV_SYN_IMAGE_VERIFY_ALLOW_LOCAL_IMAGES}=true to run images "
            "that are already built on this Docker host."
        )
        raise ImageVerificationError(msg)

    image_id = _resolve_local_image_id(image_ref)
    logger.warning(
        "Running unverified local workspace image %s as %s (%s=true): it "
        "carries no signature, and it is run by image ID so nothing can be "
        "pulled or retagged in its place",
        image_ref,
        image_id,
        ENV_SYN_IMAGE_VERIFY_ALLOW_LOCAL_IMAGES,
    )
    return image_id


def _require_digest_pin(image_ref: str) -> None:
    """Raise unless a registry reference names an immutable digest."""
    if _split_digest(image_ref) is not None:
        return
    msg = (
        f"Workspace image {image_ref!r} is a registry reference pinned by tag. "
        "Tags are mutable, so verifying one does not establish what will be "
        "pulled. Pin the digest (registry/name@sha256:...) - see "
        "syn_shared.settings.workspace_images for the current pins and the "
        "bump procedure."
    )
    raise ImageVerificationError(msg)


def _build_verify_command(
    image_ref: str,
    settings: ImageVerificationSettings,
    verifier: _Verifier,
) -> list[str]:
    """Assemble the cosign invocation for a digest-pinned registry reference."""
    command = [verifier.path, "verify"]
    # The publisher's cosign stores the signature as a Sigstore bundle under
    # the 'sha256-<digest>' tag rather than the legacy 'sha256-<digest>.sig'
    # tag. Without this flag cosign looks only for the legacy tag and reports
    # "no signatures found" for every image, which would make the control fail
    # 100% of the time and guarantee somebody turns it off. Confirmed against
    # GHCR on 2026-08-17: verification of both pinned digests passes with the
    # flag and reports "no signatures found" without it.
    if settings.new_bundle_format:
        command.append("--new-bundle-format")
    command += [
        "--certificate-identity-regexp",
        settings.certificate_identity_regexp,
        "--certificate-oidc-issuer",
        settings.certificate_oidc_issuer,
        image_ref,
    ]
    return command


def _run_cosign_verify(
    image_ref: str,
    settings: ImageVerificationSettings,
    verifier: _Verifier,
) -> None:
    """Run cosign verify, raising ImageVerificationError on any non-success."""
    command = _build_verify_command(image_ref, settings, verifier)
    logger.info("Verifying workspace image signature: %s", image_ref)
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=settings.timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        msg = (
            f"Signature verification for {image_ref} timed out after "
            f"{settings.timeout_seconds}s. A timeout is a verification failure: "
            "the image is not run."
        )
        raise ImageVerificationError(msg) from exc
    except OSError as exc:
        msg = f"Could not execute cosign at {verifier.path!r} to verify {image_ref}: {exc}"
        raise ImageVerificationError(msg) from exc

    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        msg = (
            f"Signature verification FAILED for {image_ref} "
            f"(cosign exit {completed.returncode}). Expected a signature from "
            f"identity matching {settings.certificate_identity_regexp!r} issued by "
            f"{settings.certificate_oidc_issuer}. The image is not run. "
            f"cosign said: {detail}"
        )
        raise ImageVerificationError(msg)


def verify_image(
    image_ref: str,
    settings: ImageVerificationSettings | None = None,
) -> str:
    """Verify ``image_ref`` and return the reference that must actually be run.

    This is BLOCKING: it shells out to cosign, which talks to the registry and
    the Sigstore transparency log. Never call it directly from a coroutine;
    ``verify_image_async`` is the wrapper that keeps it off the event loop.

    Args:
        image_ref: The reference the caller intends to hand to Docker.
        settings: Verification settings. Defaults to a freshly read
            ``ImageVerificationSettings`` (SYN_IMAGE_VERIFY_* env vars).

    Returns:
        The reference to run. For a verified registry image this is
        ``image_ref`` unchanged. For a permitted local image it is that image's
        immutable local image ID, which the caller MUST run in place of the
        reference it passed in.

    Raises:
        ImageVerificationError: If verification fails, if cosign is unavailable
            or is not cosign, if a registry reference is not digest-pinned, or
            if the reference has no registry host and local images are not
            enabled (or the image is not present locally).
    """
    settings = settings or ImageVerificationSettings()

    if not settings.enabled:
        logger.warning(
            "Workspace image signature verification is DISABLED (%s=false); running %s unverified",
            ENV_SYN_IMAGE_VERIFY_ENABLED,
            image_ref,
        )
        return image_ref

    if not has_registry_host(image_ref):
        return _resolve_local_reference(image_ref, settings)

    _require_digest_pin(image_ref)

    verifier = _resolve_verifier(settings)
    key = _policy_key(image_ref, settings, verifier)
    with _cache_lock:
        if key in _verified_policies:
            return image_ref

    # Deliberately OUTSIDE the lock. cosign is a network round trip, and
    # holding a process-wide mutex across it would serialise every concurrent
    # provision behind the slowest verification. Two provisions racing on the
    # same policy key simply both run cosign and both record the same result,
    # which costs one redundant check and cannot produce a wrong answer. The
    # lock guards only the set itself.
    _run_cosign_verify(image_ref, settings, verifier)

    with _cache_lock:
        _verified_policies.add(key)

    logger.info("Workspace image signature verified: %s", image_ref)
    return image_ref


async def verify_image_async(
    image_ref: str,
    settings: ImageVerificationSettings | None = None,
) -> str:
    """Await ``verify_image`` on a worker thread, returning what should run.

    ``verify_image`` blocks on a subprocess that performs registry and Rekor
    transparency-log lookups, for up to ``timeout_seconds``. Called straight
    from a coroutine that would stall the whole event loop, which in an
    orchestrator means every unrelated execution stalls behind one cold image
    verification. Off-loading it keeps provisioning concurrent.

    This changes only where the work runs. Exceptions raised in the worker
    thread propagate out of the await, so a verification failure still stops
    the caller before any container is created.
    """
    return await asyncio.to_thread(verify_image, image_ref, settings)
