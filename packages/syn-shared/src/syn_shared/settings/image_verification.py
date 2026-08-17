"""Container image signature verification settings (cosign keyless / Sigstore).

agentic-primitives signs every published workspace image with cosign keyless
OIDC at build time (``.github/workflows/build-workspace-images.yml``, the
"Sign image with cosign" step). Until this module existed nothing on the
Syntropic137 side checked those signatures, which made them evidence nobody
read.

Keyless verification is only meaningful with identity constraints. A bare
``cosign verify`` with no ``--certificate-identity`` and no
``--certificate-oidc-issuer`` is rejected by cosign v2, and a wrong constraint
either always fails or pins to the wrong signer. The defaults below are read
off the publishing workflow, not guessed:

- The issuer is GitHub's Actions OIDC provider,
  ``https://token.actions.githubusercontent.com``.
- The certificate identity (the SAN on the Fulcio cert) for a GitHub Actions
  keyless signature is the workflow reference:
  ``https://github.com/<owner>/<repo>/<workflow path>@<git ref>``.
  For this publisher that is
  ``https://github.com/AgentParadise/agentic-primitives/.github/workflows/build-workspace-images.yml@refs/heads/main``.

The default is a regexp rather than an exact identity for one reason: the
publishing branch is planned to move from ``main`` to a protected ``release``
branch. The regexp admits exactly those two refs of exactly that workflow in
exactly that repository, so the branch move does not require an emergency
config change while still naming the signer precisely. It does not admit any
other workflow, repository, or ref.

Environment Variables:
    SYN_IMAGE_VERIFY_* - signature verification configuration
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

#: OIDC issuer for GitHub Actions keyless signing.
GITHUB_ACTIONS_OIDC_ISSUER = "https://token.actions.githubusercontent.com"

#: Certificate identity (SAN) regexp for the agentic-primitives image publisher.
#: Anchored at both ends so it matches the whole SAN, not a substring.
AGENTIC_PRIMITIVES_IDENTITY_REGEXP = (
    r"^https://github\.com/AgentParadise/agentic-primitives"
    r"/\.github/workflows/build-workspace-images\.yml"
    r"@refs/heads/(main|release)$"
)


class ImageVerificationSettings(BaseSettings):
    """Configuration for verifying workspace image signatures before use.

    Override via ``SYN_IMAGE_VERIFY_*`` environment variables.

    Example:
        # Default: verification on, failing closed.

        # Emergency opt-out (recorded, deliberate, logged at WARNING):
        SYN_IMAGE_VERIFY_ENABLED=false
    """

    model_config = SettingsConfigDict(
        env_prefix="SYN_IMAGE_VERIFY_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    enabled: bool = Field(
        default=True,
        description=(
            "Verify the cosign signature of a remote workspace image before "
            "running it. ON by default and fails closed. Setting this to false "
            "disables a security control and is logged at WARNING every time a "
            "workspace is provisioned."
        ),
    )

    certificate_identity_regexp: str = Field(
        default=AGENTIC_PRIMITIVES_IDENTITY_REGEXP,
        description=(
            "Regexp matched against the signing certificate identity (SAN). "
            "For GitHub Actions keyless signing this is the workflow reference "
            "'https://github.com/<owner>/<repo>/<workflow path>@<git ref>'. "
            "Change this only when pointing at a different publisher."
        ),
    )

    certificate_oidc_issuer: str = Field(
        default=GITHUB_ACTIONS_OIDC_ISSUER,
        description=(
            "OIDC issuer that must have issued the signing certificate. "
            "GitHub Actions keyless signing always uses "
            "https://token.actions.githubusercontent.com"
        ),
    )

    new_bundle_format: bool = Field(
        default=True,
        description=(
            "Pass --new-bundle-format to cosign verify. Required for these "
            "images: the publisher's cosign writes the signature as a Sigstore "
            "bundle under the 'sha256-<digest>' tag, not the legacy "
            "'sha256-<digest>.sig' tag, and without this flag verification "
            "fails with 'no signatures found' for every image. Set false only "
            "when verifying images signed by an older cosign."
        ),
    )

    cosign_path: str = Field(
        default="cosign",
        description=(
            "cosign executable, resolved on PATH unless an absolute path is "
            "given. cosign v2 or later is required: the "
            "--certificate-identity-regexp flag does not exist in v1."
        ),
    )

    timeout_seconds: float = Field(
        default=60.0,
        gt=0,
        description=(
            "Timeout for a single cosign verify invocation. Verification "
            "contacts the registry and the Sigstore transparency log, so this "
            "is a network-bound call. A timeout is a verification failure."
        ),
    )
