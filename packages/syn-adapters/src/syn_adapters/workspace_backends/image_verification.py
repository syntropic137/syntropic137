"""Verify workspace image signatures with cosign before a container is created.

agentic-primitives signs every published workspace image with cosign keyless
OIDC. This module is the consumer half of that: it runs ``cosign verify``
against the exact digest that is about to be run, with the publisher's identity
constraints, and raises if verification does not succeed.

Policy
------
Given the image reference the adapter is about to hand to Docker:

1. **Local reference** (no registry host, e.g. ``agentic-workspace-claude-cli:dev``)
   Skipped, with a WARNING. A locally built image was never published and
   therefore cannot carry a Sigstore signature. This is the supported local
   development path; failing here would only teach people to switch the
   control off.
2. **Remote reference pinned by digest** (``ghcr.io/...@sha256:...``)
   Verified. Any failure - bad signature, wrong signer, no signature, cosign
   missing, cosign timing out - raises ``ImageVerificationError`` and the
   container is not created.
3. **Remote reference by tag** (``ghcr.io/...:latest``)
   Rejected. Verifying a tag does not establish what will be pulled: the tag
   can move between the verify call and the pull, and cosign would be attesting
   to a digest that is not necessarily the one Docker resolves. Pin the digest.

Missing cosign is a hard failure, not a warned skip
---------------------------------------------------
For remote images, ``cosign`` not being installed produces the same outcome as
a forged signature would if we skipped: an unverified image runs. A warning in
a log nobody is reading is not a control, and "the tool was missing" is the
single most likely way this check would silently stop working. So it fails
closed.

The cost of that strictness is bounded and deliberate:

- Local development is unaffected, because local images take path 1 above.
- An operator who genuinely cannot install cosign has one explicit, recorded
  switch, ``SYN_IMAGE_VERIFY_ENABLED=false``, which logs a WARNING on every
  provision. That is a decision someone makes on purpose, not a control that
  evaporates because a binary is absent from a base image.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import threading

from syn_adapters.workspace_backends.errors import WorkspaceProvisionError
from syn_shared.settings.image_verification import ImageVerificationSettings

logger = logging.getLogger(__name__)

__all__ = [
    "ImageVerificationError",
    "is_remote_reference",
    "reset_verification_cache",
    "verify_image",
]


class ImageVerificationError(WorkspaceProvisionError):
    """Raised when a workspace image fails signature verification.

    Subclasses ``WorkspaceProvisionError`` so the existing error-mapping layers
    (``_fail_execution``, ``syn execution show``) surface it with execution
    context, while callers that care specifically about a supply-chain failure
    can still match the narrower type.
    """


# Verification is a network round trip to the registry and the Sigstore
# transparency log, and the same image is provisioned many times. Successful
# results are cached for the process lifetime, keyed by the full digest
# reference - which is safe precisely because a digest reference is immutable.
# Failures are deliberately NOT cached: a failure can be transient (network,
# timeout) and caching it would turn a blip into a sticky outage.
_verified_refs: set[str] = set()
_cache_lock = threading.Lock()


def reset_verification_cache() -> None:
    """Clear the successful-verification cache. For tests."""
    with _cache_lock:
        _verified_refs.clear()


def is_remote_reference(image_ref: str) -> bool:
    """Return True if the reference names a registry host.

    Uses the standard OCI rule: a reference has a registry host only if it
    contains a '/' AND its first component contains a '.' or a ':' (a port), or
    is exactly 'localhost'.

    The '/' requirement matters. Without it, the tag separator in a bare name
    like ``agentic-workspace-claude-cli:dev`` reads as a port and the local
    development image gets misclassified as remote, which would then be
    rejected for not being digest-pinned. Anything with no '/'
    (``agentic-workspace-claude-cli:dev``) or a plain first component
    (``library/python``) is a local or Docker Hub short name, and for our
    purposes a local one.
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


def verify_image(
    image_ref: str,
    settings: ImageVerificationSettings | None = None,
) -> None:
    """Verify the signature of ``image_ref``, or raise.

    Args:
        image_ref: The exact reference about to be passed to Docker.
        settings: Verification settings. Defaults to a freshly read
            ``ImageVerificationSettings`` (SYN_IMAGE_VERIFY_* env vars).

    Raises:
        ImageVerificationError: If the image is remote and its signature
            cannot be verified, if cosign is unavailable, or if the reference
            is remote but not digest-pinned.
    """
    settings = settings or ImageVerificationSettings()

    if not settings.enabled:
        logger.warning(
            "Workspace image signature verification is DISABLED "
            "(SYN_IMAGE_VERIFY_ENABLED=false); running %s unverified",
            image_ref,
        )
        return

    if not is_remote_reference(image_ref):
        logger.warning(
            "Skipping signature verification for local image %s: a locally "
            "built image is not published and carries no Sigstore signature",
            image_ref,
        )
        return

    digest = _split_digest(image_ref)
    if digest is None:
        msg = (
            f"Workspace image {image_ref!r} is a remote reference pinned by tag. "
            "Tags are mutable, so verifying one does not establish what will be "
            "pulled. Pin the digest (registry/name@sha256:...) - see "
            "syn_shared.settings.workspace_images for the current pins and the "
            "bump procedure."
        )
        raise ImageVerificationError(msg)

    with _cache_lock:
        if image_ref in _verified_refs:
            return

    cosign = shutil.which(settings.cosign_path) or (
        settings.cosign_path if "/" in settings.cosign_path else None
    )
    if cosign is None:
        msg = (
            f"Cannot verify workspace image {image_ref}: cosign executable "
            f"{settings.cosign_path!r} was not found on PATH. Signature "
            "verification fails closed, because a missing verifier and a "
            "forged signature have the same outcome if the check is skipped. "
            "Install cosign v2 (https://docs.sigstore.dev/cosign/installation/), "
            "or set SYN_IMAGE_VERIFY_ENABLED=false to accept unverified images "
            "deliberately."
        )
        raise ImageVerificationError(msg)

    command = [cosign, "verify"]
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
        msg = f"Could not execute cosign at {cosign!r} to verify {image_ref}: {exc}"
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

    with _cache_lock:
        _verified_refs.add(image_ref)

    logger.info("Workspace image signature verified: %s", image_ref)
