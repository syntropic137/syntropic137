"""The nested-Docker E2B template is referenced by its pinned inputs (AW#91).

No real E2B: the real ``E2BWorkspaceProvider`` runs over ``SandboxDouble``.
Covers the derived template name, the startup drift refusal, the settings
reaching the provider, and Syn137's floor matching agentic-workspace's.
"""

from __future__ import annotations

import dataclasses

import pytest
from agentic_isolation.providers.e2b import _DOCKER_READY
from agentic_isolation.providers.e2b_template import NESTED_DOCKER, DockerEngine, PrePull

from syn_adapters.workspace_backends.agentic import AgenticIsolationAdapter
from syn_adapters.workspace_backends.e2b import e2b_conformance as suite
from syn_adapters.workspace_backends.e2b import template_ref
from syn_adapters.workspace_backends.e2b.test_e2b_backend import SandboxDouble
from syn_adapters.workspace_backends.errors import WorkspaceProvisionError
from syn_adapters.workspace_backends.service import WorkspaceBackend, WorkspaceService
from syn_shared.settings import e2b as e2b_settings
from syn_shared.settings.e2b import E2BSettings
from syn_shared.settings.workspace_images import (
    E2B_DOCKER_PRE_PULLS,
    E2B_DOCKER_TEMPLATE_PROVIDER,
    PINNED_DIGESTS,
    WorkspaceImageProvider,
)

pytestmark = pytest.mark.unit

_KEY = "e2b_test_key_not_real"
_DIGEST = "sha256:" + "ab" * 32
_OTHER_DIGEST = "sha256:" + "cd" * 32
_SETTINGS = (
    "ENABLED",
    "API_KEY",
    "TEMPLATE",
    "CPU_COUNT",
    "MEMORY_MB",
    "TIMEOUT_SECONDS",
    "NESTED_DOCKER",
    "DOCKER_READY_SECONDS",
)


def _docker_settings(monkeypatch: pytest.MonkeyPatch, **env: str) -> E2BSettings:
    for name in _SETTINGS:
        monkeypatch.delenv(f"SYN_E2B_{name}", raising=False)
    base = {
        "ENABLED": "true",
        "API_KEY": _KEY,
        "TEMPLATE": template_ref.expected_template_name(),
        "CPU_COUNT": "2",
        "MEMORY_MB": "4096",
        "NESTED_DOCKER": "true",
    }
    for name, value in {**base, **env}.items():
        monkeypatch.setenv(f"SYN_E2B_{name}", value)
    return E2BSettings(_env_file=None)  # type: ignore[call-arg]


# --- name derivation ------------------------------------------------------


def test_the_name_is_image_digest12_and_engine_hash8() -> None:
    engine = DockerEngine()
    name = template_ref.template_name(WorkspaceImageProvider.TOOLCHAIN, _DIGEST, engine)
    assert name == f"syn137-toolchain-{'ab' * 6}-docker-{template_ref.engine_hash(engine)}"
    assert len(template_ref.engine_hash(engine)) == 8


def test_the_expected_name_is_derived_from_the_current_pins() -> None:
    digest = PINNED_DIGESTS[E2B_DOCKER_TEMPLATE_PROVIDER].removeprefix("sha256:")
    assert template_ref.expected_template_name() == (
        f"syn137-{E2B_DOCKER_TEMPLATE_PROVIDER.value}-{digest[:12]}-docker-"
        f"{template_ref.engine_hash(template_ref.pinned_docker_engine())}"
    )


def test_a_base_digest_bump_yields_a_new_name() -> None:
    engine = DockerEngine()
    provider = WorkspaceImageProvider.TOOLCHAIN
    assert template_ref.template_name(provider, _DIGEST, engine) != template_ref.template_name(
        provider, _OTHER_DIGEST, engine
    )


def test_a_pre_pull_change_yields_a_new_name() -> None:
    plain = DockerEngine()
    pulled = DockerEngine(pre_pull=(PrePull("postgres:16", _DIGEST),))
    repinned = DockerEngine(pre_pull=(PrePull("postgres:16", _OTHER_DIGEST),))
    assert len({template_ref.engine_hash(e) for e in (plain, pulled, repinned)}) == 3


def test_an_engine_version_change_yields_a_new_name() -> None:
    engine = DockerEngine()
    bumped = dataclasses.replace(engine, compose_version="5.6.2-1~debian.12~bookworm")
    assert template_ref.engine_hash(engine) != template_ref.engine_hash(bumped)


def test_a_digest_without_its_algorithm_is_refused() -> None:
    with pytest.raises(ValueError, match="sha256"):
        template_ref.template_name(WorkspaceImageProvider.TOOLCHAIN, "ab" * 32, DockerEngine())


def test_the_pinned_engine_pre_pulls_every_pin_by_digest() -> None:
    engine = template_ref.pinned_docker_engine()
    assert [(p.reference, p.digest) for p in engine.pre_pull] == [
        (p.reference, p.digest) for p in E2B_DOCKER_PRE_PULLS
    ]
    assert any(p.reference.startswith("ghcr.io/syntropic137/event-store:") for p in engine.pre_pull)


def test_the_pinned_spec_is_built_from_the_pinned_base_digest() -> None:
    spec = template_ref.pinned_template_spec(
        expected_manifest_hash=_DIGEST, cpu_count=2, memory_mb=4096
    )
    assert spec.name == template_ref.expected_template_name()
    assert spec.verified_oci_digest == PINNED_DIGESTS[E2B_DOCKER_TEMPLATE_PROVIDER]
    assert spec.image.endswith("@" + spec.verified_oci_digest)
    assert spec.docker == template_ref.pinned_docker_engine()


def test_syn137s_docker_floor_is_agentic_workspaces() -> None:
    engine = DockerEngine()
    assert engine.min_cpu_count == e2b_settings.NESTED_DOCKER_MIN_CPU_COUNT
    assert engine.min_memory_mb == e2b_settings.NESTED_DOCKER_MIN_MEMORY_MB


# --- drift guard at startup ----------------------------------------------


def test_a_template_not_named_by_the_current_pins_refuses_to_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    double = SandboxDouble()
    stale = template_ref.template_name(
        E2B_DOCKER_TEMPLATE_PROVIDER, _OTHER_DIGEST, template_ref.pinned_docker_engine()
    )
    settings = _docker_settings(monkeypatch, TEMPLATE=stale)
    with pytest.raises(template_ref.E2BTemplateDriftError, match="just e2b-template-build"):
        WorkspaceService.create(backend=WorkspaceBackend.E2B, e2b=settings, e2b_client=double)
    assert double.created_from == []


def test_without_nested_docker_any_template_name_is_accepted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _docker_settings(monkeypatch, TEMPLATE="operator-template", NESTED_DOCKER="false")
    WorkspaceService.create(backend=WorkspaceBackend.E2B, e2b=settings, e2b_client=SandboxDouble())


# --- the settings reach the provider -------------------------------------


async def test_the_current_template_starts_and_advertises_nested_docker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    double = SandboxDouble()
    double.script[_DOCKER_READY] = ("29.9.2\n", 0)
    service = WorkspaceService.create(
        backend=WorkspaceBackend.E2B, e2b=_docker_settings(monkeypatch), e2b_client=double
    )
    isolation = service._isolation
    assert isinstance(isolation, AgenticIsolationAdapter)
    assert NESTED_DOCKER in isolation.operations.describe().capabilities
    handle = await isolation.create(suite.isolation_config(service._config.image))
    assert double.created_from == [template_ref.expected_template_name()]
    await isolation.destroy(handle)


async def test_docker_ready_seconds_bounds_the_wait_for_docker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    double = SandboxDouble()  # `docker info` answers nothing: never ready
    service = WorkspaceService.create(
        backend=WorkspaceBackend.E2B,
        e2b=_docker_settings(monkeypatch, DOCKER_READY_SECONDS="0.2"),
        e2b_client=double,
    )
    isolation = service._isolation
    assert isinstance(isolation, AgenticIsolationAdapter)
    with pytest.raises((RuntimeError, WorkspaceProvisionError), match=r"within 0\.2s"):
        await isolation.create(suite.isolation_config(service._config.image))
    assert double.sandboxes == {}
