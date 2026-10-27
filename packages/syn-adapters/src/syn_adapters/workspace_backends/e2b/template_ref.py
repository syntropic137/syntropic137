"""How Syn137 references the nested-Docker E2B template (AgentParadise/agentic-workspace#91).

An E2B template lives in the operator's E2B account: agentic-workspace ships
the code that builds it (``DockerEngine``, ``build_template``) and the signed
workspace image, and the template id is minted when the operator builds in
their own account. So Syn137 never hard-codes a template. It pins the INPUTS
(``syn_shared.settings.workspace_images``: the base image's PINNED_DIGESTS
entry and the pre-pulls) and derives the template NAME from them::

    syn137-<image>-<digest12>-docker-<engine-hash8>

``<engine-hash8>`` hashes every field of the ``DockerEngine`` (package
versions, apt key, user, floor, pre-pulls), so a PINNED_DIGESTS bump, a
pre-pull change or an agentic-workspace engine change each yield a new name.

The drift guard is the cheap variant: with ``SYN_E2B_NESTED_DOCKER`` on,
``SYN_E2B_TEMPLATE`` must equal the derived name, or the E2B backend refuses
to start. A template built from older pins carries an older name, so it is
refused rather than run silently stale. What the guard does NOT prove: that a
template of that name was actually built from those inputs. Only the build
(``just e2b-template-build``) names templates this way, and its receipt
records what it built.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json

from agentic_isolation.providers.e2b_template import DockerEngine, E2BTemplateSpec, PrePull

from syn_shared.settings.workspace_images import (
    E2B_DOCKER_PRE_PULLS,
    E2B_DOCKER_TEMPLATE_PROVIDER,
    PINNED_DIGESTS,
    WorkspaceImageProvider,
    workspace_image_ref,
)

_DIGEST_PREFIX = "sha256:"


class E2BTemplateDriftError(ValueError):
    """``SYN_E2B_TEMPLATE`` is not the template the current pins derive."""


def pinned_docker_engine() -> DockerEngine:
    """agentic-workspace's engine at its pinned versions, with Syn137's pre-pulls."""
    return DockerEngine(
        pre_pull=tuple(PrePull(pin.reference, pin.digest) for pin in E2B_DOCKER_PRE_PULLS)
    )


def engine_hash(engine: DockerEngine) -> str:
    """The first 8 hex of sha256 over every field of ``engine``, canonically serialised."""
    canonical = json.dumps(dataclasses.asdict(engine), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()[:8]


def template_name(provider: WorkspaceImageProvider, digest: str, engine: DockerEngine) -> str:
    """``syn137-<image>-<digest12>-docker-<engine-hash8>`` for these inputs."""
    if not digest.startswith(_DIGEST_PREFIX):
        msg = f"base digest {digest!r} is not sha256:<hex>"
        raise ValueError(msg)
    digest12 = digest.removeprefix(_DIGEST_PREFIX)[:12]
    return f"syn137-{provider.value}-{digest12}-docker-{engine_hash(engine)}"


def expected_template_name() -> str:
    """The template name the current pins derive."""
    return template_name(
        E2B_DOCKER_TEMPLATE_PROVIDER,
        PINNED_DIGESTS[E2B_DOCKER_TEMPLATE_PROVIDER],
        pinned_docker_engine(),
    )


def pinned_template_spec(
    *, expected_manifest_hash: str, cpu_count: int, memory_mb: int
) -> E2BTemplateSpec:
    """The ``build_template`` spec for the current pins, named by ``expected_template_name``.

    ``expected_manifest_hash`` is the sha256 of the base image's version.json,
    read by the caller from the verified digest.
    """
    digest = PINNED_DIGESTS[E2B_DOCKER_TEMPLATE_PROVIDER]
    return E2BTemplateSpec(
        name=expected_template_name(),
        image=workspace_image_ref(E2B_DOCKER_TEMPLATE_PROVIDER),
        verified_oci_digest=digest,
        expected_manifest_hash=expected_manifest_hash,
        cpu_count=cpu_count,
        memory_mb=memory_mb,
        docker=pinned_docker_engine(),
    )


def require_current_template(template: str) -> None:
    """Refuse a nested-Docker template that the current pins did not name."""
    expected = expected_template_name()
    if template != expected:
        msg = (
            f"SYN_E2B_NESTED_DOCKER is true but SYN_E2B_TEMPLATE={template!r} is not the "
            f"template the current pins derive ({expected!r}). It was built from other "
            "inputs (an older PINNED_DIGESTS entry, pre-pull or Docker engine), and Syn137 "
            "does not run a stale template. Build the current one with "
            "`just e2b-template-build` and set SYN_E2B_TEMPLATE to the name it prints."
        )
        raise E2BTemplateDriftError(msg)
