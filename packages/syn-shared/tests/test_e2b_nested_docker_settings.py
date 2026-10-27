"""SYN_E2B_NESTED_DOCKER refuses a template too small for Docker (AW#91)."""

from __future__ import annotations

import re

import pytest
from pydantic import ValidationError

from syn_shared.settings.e2b import (
    NESTED_DOCKER_MIN_CPU_COUNT,
    NESTED_DOCKER_MIN_MEMORY_MB,
    E2BSettings,
)
from syn_shared.settings.workspace_images import (
    DEFAULT_WORKSPACE_PROVIDER,
    E2B_DOCKER_PRE_PULLS,
    E2B_DOCKER_TEMPLATE_PROVIDER,
    PINNED_DIGESTS,
)

pytestmark = pytest.mark.unit

_NAMES = (
    "ENABLED",
    "API_KEY",
    "TEMPLATE",
    "CPU_COUNT",
    "MEMORY_MB",
    "TIMEOUT_SECONDS",
    "NESTED_DOCKER",
    "DOCKER_READY_SECONDS",
)
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")


def _settings(monkeypatch: pytest.MonkeyPatch, **env: str) -> E2BSettings:
    for name in _NAMES:
        monkeypatch.delenv(f"SYN_E2B_{name}", raising=False)
    for name, value in env.items():
        monkeypatch.setenv(f"SYN_E2B_{name}", value)
    return E2BSettings(_env_file=None)  # type: ignore[call-arg]


def test_nested_docker_is_off_with_a_30s_readiness_bound_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings(monkeypatch)
    assert settings.nested_docker is False
    assert settings.docker_ready_seconds == 30.0


def test_nested_docker_at_the_floor_loads(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings(
        monkeypatch,
        NESTED_DOCKER="true",
        CPU_COUNT=str(NESTED_DOCKER_MIN_CPU_COUNT),
        MEMORY_MB=str(NESTED_DOCKER_MIN_MEMORY_MB),
    )
    assert settings.nested_docker is True


@pytest.mark.parametrize(
    ("cpu", "memory"),
    [
        (NESTED_DOCKER_MIN_CPU_COUNT - 1, NESTED_DOCKER_MIN_MEMORY_MB),
        (NESTED_DOCKER_MIN_CPU_COUNT, NESTED_DOCKER_MIN_MEMORY_MB - 1),
    ],
)
def test_nested_docker_below_the_floor_refuses_to_load(
    monkeypatch: pytest.MonkeyPatch, cpu: int, memory: int
) -> None:
    with pytest.raises(ValidationError, match="SYN_E2B_NESTED_DOCKER"):
        _settings(monkeypatch, NESTED_DOCKER="true", CPU_COUNT=str(cpu), MEMORY_MB=str(memory))


def test_a_small_template_without_nested_docker_still_loads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert _settings(monkeypatch, CPU_COUNT="1", MEMORY_MB="2048").nested_docker is False


@pytest.mark.parametrize("seconds", ["0", "-1"])
def test_a_non_positive_docker_readiness_bound_refuses_to_load(
    monkeypatch: pytest.MonkeyPatch, seconds: str
) -> None:
    with pytest.raises(ValidationError, match="docker_ready_seconds"):
        _settings(monkeypatch, DOCKER_READY_SECONDS=seconds)


def test_the_template_base_is_a_pinned_digest_entry() -> None:
    assert E2B_DOCKER_TEMPLATE_PROVIDER == DEFAULT_WORKSPACE_PROVIDER
    assert E2B_DOCKER_TEMPLATE_PROVIDER in PINNED_DIGESTS


def test_every_pre_pull_is_a_digest_and_none_is_latest() -> None:
    assert E2B_DOCKER_PRE_PULLS
    for pin in E2B_DOCKER_PRE_PULLS:
        assert _DIGEST.fullmatch(pin.digest), pin
        assert "${" not in pin.reference and not pin.reference.endswith(":latest"), pin
