"""Build the nested-Docker E2B template from the current pins (AgentParadise/agentic-workspace#91).

Run by ``just e2b-template-build``, by hand, with the operator's own E2B key.
Never in CI: no E2B key exists there (owner rule).

An E2B template lives in the operator's E2B account, so Syn137 pins the
INPUTS and this builds from them: the base image's PINNED_DIGESTS entry, the
digest-pinned pre-pulls and agentic-workspace's ``DockerEngine``. The template
is named from those inputs (``syn_adapters.workspace_backends.e2b.template_ref``),
so the name this prints is the one ``SYN_E2B_TEMPLATE`` must hold; a template
built from older pins is refused at startup.

Steps, every one fail-closed:

1. cosign-verify the base image digest (Syn137's ``verify_image``, the policy
   every Docker workspace gets). ``build_template`` takes the verified digest.
2. Read ``/opt/agentic/version.json`` out of that digest (linux/amd64, the
   platform E2B runs) and hash it with agentic-workspace's ``manifest_hash``.
3. ``build_template`` on E2B.
4. Write a receipt, ``<receipt-dir>/<name>.json``: what E2B named the build and
   every input it was built from.

The API key is read by the e2b SDK from ``E2B_API_KEY``; when only
``SYN_E2B_API_KEY`` is set it is copied there for this process. It is never an
argument, so no traceback can print it.

Usage:

    e2b_template_build.py --name-only                 # print the derived name
    e2b_template_build.py [--cpu-count N] [--memory-mb N] [--receipt-dir DIR]
"""

from __future__ import annotations

import argparse
import asyncio
import os
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from pydantic import BaseModel, ConfigDict

from syn_adapters.workspace_backends.e2b.template_ref import (
    engine_hash,
    expected_template_name,
    pinned_template_spec,
)
from syn_shared.settings.e2b import NESTED_DOCKER_MIN_CPU_COUNT, NESTED_DOCKER_MIN_MEMORY_MB
from syn_shared.settings.workspace_images import (
    E2B_DOCKER_TEMPLATE_PROVIDER,
    workspace_image_ref,
)

if TYPE_CHECKING:
    from collections.abc import MutableMapping, Sequence

    from agentic_isolation.providers.e2b_template import E2BTemplateBuild, E2BTemplateSpec

#: Where the version manifest sits in every workspace image.
MANIFEST_PATH = "/opt/agentic/version.json"
#: E2B runs x86_64 Firecracker VMs; the manifest is read from that platform's image.
E2B_PLATFORM = "linux/amd64"
SDK_KEY_VARIABLE = "E2B_API_KEY"
SYN_KEY_VARIABLE = "SYN_E2B_API_KEY"
DEFAULT_RECEIPT_DIR = Path(".e2b-templates")
_DOCKER_TIMEOUT_SECONDS = 600


class TemplateBuildError(RuntimeError):
    """The template could not be built from the current pins. Always fatal."""


class BaseImageReader(Protocol):
    """What the build needs to know about the base image before trusting it."""

    def verify(self, image: str) -> None:
        """Raise unless ``image`` passes signature verification."""
        ...

    def manifest_hash(self, image: str) -> str:
        """``sha256:<hex>`` of ``MANIFEST_PATH`` inside ``image``."""
        ...


class TemplateBuilder(Protocol):
    async def build(self, spec: E2BTemplateSpec) -> E2BTemplateBuild: ...


class PrePullReceipt(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    reference: str
    digest: str


class TemplateReceipt(BaseModel):
    """What one build produced and every input it was built from."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    template_id: str
    build_id: str
    image: str
    verified_oci_digest: str
    expected_manifest_hash: str
    cpu_count: int
    memory_mb: int
    engine_hash: str
    docker_versions: dict[str, str]
    pre_pull: tuple[PrePullReceipt, ...]
    built_at: str


def bridge_sdk_key(environ: MutableMapping[str, str]) -> None:
    """Make ``SYN_E2B_API_KEY`` visible to the SDK as ``E2B_API_KEY``; refuse neither."""
    if environ.get(SDK_KEY_VARIABLE):
        return
    key = environ.get(SYN_KEY_VARIABLE)
    if not key:
        msg = f"set {SYN_KEY_VARIABLE} (or {SDK_KEY_VARIABLE}) to build an E2B template"
        raise TemplateBuildError(msg)
    environ[SDK_KEY_VARIABLE] = key


async def build(
    reader: BaseImageReader,
    builder: TemplateBuilder,
    *,
    cpu_count: int,
    memory_mb: int,
    receipt_dir: Path,
) -> TemplateReceipt:
    """Verify the base, build the template, write and return its receipt."""
    image = workspace_image_ref(E2B_DOCKER_TEMPLATE_PROVIDER)
    reader.verify(image)
    spec = pinned_template_spec(
        expected_manifest_hash=reader.manifest_hash(image),
        cpu_count=cpu_count,
        memory_mb=memory_mb,
    )
    if spec.docker is None:  # pragma: no cover - pinned_template_spec always sets it
        msg = "the pinned template spec has no Docker engine"
        raise TemplateBuildError(msg)
    built = await builder.build(spec)
    receipt = TemplateReceipt(
        name=spec.name,
        template_id=built.template_id,
        build_id=built.build_id,
        image=spec.image,
        verified_oci_digest=spec.verified_oci_digest,
        expected_manifest_hash=spec.expected_manifest_hash,
        cpu_count=spec.cpu_count,
        memory_mb=spec.memory_mb,
        engine_hash=engine_hash(spec.docker),
        docker_versions=spec.docker.expected_versions(),
        pre_pull=tuple(
            PrePullReceipt(reference=p.reference, digest=p.digest) for p in spec.docker.pre_pull
        ),
        built_at=datetime.now(UTC).isoformat(),
    )
    receipt_dir.mkdir(parents=True, exist_ok=True)
    (receipt_dir / f"{spec.name}.json").write_text(receipt.model_dump_json(indent=2) + "\n")
    return receipt


# --- the real collaborators (not unit-tested: they need a registry and E2B) ---


def _docker(*args: str) -> str:
    try:
        done = subprocess.run(
            ["docker", *args],
            capture_output=True,
            text=True,
            check=False,
            timeout=_DOCKER_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        msg = f"docker {args[0]} could not run: {exc}"
        raise TemplateBuildError(msg) from exc
    if done.returncode != 0:
        msg = f"docker {args[0]} failed: {(done.stderr or done.stdout).strip()[:400]}"
        raise TemplateBuildError(msg)
    return done.stdout.strip()


class DockerBaseImageReader:
    def verify(self, image: str) -> None:
        from syn_adapters.workspace_backends.image_verification import verify_image
        from syn_shared.settings.image_verification import ImageVerificationSettings

        settings = ImageVerificationSettings()
        if not settings.enabled:
            # verify_image would only warn; the template's digest must be verified.
            msg = "image verification is disabled (SYN_IMAGE_VERIFY_ENABLED=false)"
            raise TemplateBuildError(msg)
        if verify_image(image, settings) != image:
            msg = f"{image} did not verify as a registry image"
            raise TemplateBuildError(msg)

    def manifest_hash(self, image: str) -> str:
        from agentic_isolation.providers.e2b_template import manifest_hash

        _docker("pull", "--quiet", "--platform", E2B_PLATFORM, image)
        container = _docker("create", "--platform", E2B_PLATFORM, image)
        try:
            with tempfile.TemporaryDirectory() as scratch:
                target = Path(scratch) / "version.json"
                _docker("cp", f"{container}:{MANIFEST_PATH}", str(target))
                return manifest_hash(target)
        finally:
            _docker("rm", container)


class E2BTemplateBuilder:
    async def build(self, spec: E2BTemplateSpec) -> E2BTemplateBuild:
        from agentic_isolation.providers.e2b_template import build_template

        return await build_template(spec)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--name-only", action="store_true", help="print the derived name only")
    parser.add_argument("--cpu-count", type=int, default=NESTED_DOCKER_MIN_CPU_COUNT)
    parser.add_argument("--memory-mb", type=int, default=NESTED_DOCKER_MIN_MEMORY_MB)
    parser.add_argument("--receipt-dir", type=Path, default=DEFAULT_RECEIPT_DIR)
    args = parser.parse_args(argv)
    if args.name_only:
        print(expected_template_name())
        return 0
    try:
        bridge_sdk_key(os.environ)
        receipt = asyncio.run(
            build(
                DockerBaseImageReader(),
                E2BTemplateBuilder(),
                cpu_count=args.cpu_count,
                memory_mb=args.memory_mb,
                receipt_dir=args.receipt_dir,
            )
        )
    except (TemplateBuildError, ValueError) as exc:
        print(f"e2b-template-build: {exc}", file=sys.stderr)
        return 1
    print(f"built {receipt.name} (template {receipt.template_id}, build {receipt.build_id})")
    print(f"receipt: {args.receipt_dir / f'{receipt.name}.json'}")
    print("set in the API's environment:")
    print(f"  SYN_E2B_TEMPLATE={receipt.name}")
    print("  SYN_E2B_NESTED_DOCKER=true")
    print(f"  SYN_E2B_CPU_COUNT={receipt.cpu_count}")
    print(f"  SYN_E2B_MEMORY_MB={receipt.memory_mb}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
