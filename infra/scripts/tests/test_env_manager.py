"""Unit tests for infra/scripts/env_manager.py.

Pure logic tests - no Docker, no subprocess, no filesystem side effects.
Tests cover: slugification, port computation, slot allocation, registry
serialization, env file generation, and compose argument construction.
"""
from __future__ import annotations

import json
import pytest
from pathlib import Path
from unittest.mock import patch

# Import the module under test - patch REPO_ROOT so file operations
# use tmp_path instead of the real repo.
import infra.scripts.env_manager as em


# ---------------------------------------------------------------------------
# Slugification
# ---------------------------------------------------------------------------


class TestSlugify:
    def test_strips_feat_prefix(self) -> None:
        assert em._slugify("feat/new-triggers") == "new-triggers"

    def test_strips_feature_prefix(self) -> None:
        assert em._slugify("feature/new-triggers") == "new-triggers"

    def test_strips_fix_prefix(self) -> None:
        assert em._slugify("fix/broken-auth") == "broken-auth"

    def test_strips_chore_prefix(self) -> None:
        assert em._slugify("chore/update-deps") == "update-deps"

    def test_strips_hotfix_prefix(self) -> None:
        assert em._slugify("hotfix/critical-bug") == "critical-bug"

    def test_strips_release_prefix(self) -> None:
        assert em._slugify("release/v1.0") == "v1-0"

    def test_lowercases(self) -> None:
        # "Feature/" doesn't match the prefix regex (case-sensitive), so it stays
        assert em._slugify("Feature/MyBranch") == "feature-mybranch"

    def test_replaces_special_chars_with_hyphens(self) -> None:
        assert em._slugify("feat/my_cool.branch") == "my-cool-branch"

    def test_strips_leading_trailing_hyphens(self) -> None:
        assert em._slugify("feat/--leading-trailing--") == "leading-trailing"

    def test_plain_branch_name(self) -> None:
        assert em._slugify("my-branch") == "my-branch"

    def test_nested_slashes(self) -> None:
        assert em._slugify("feat/ISS-123/some-work") == "iss-123-some-work"


# ---------------------------------------------------------------------------
# Port computation
# ---------------------------------------------------------------------------


class TestComputePorts:
    def test_slot_2_ports(self) -> None:
        ports = em._compute_ports(2)
        assert ports.gateway == 28137
        assert ports.api == 29137
        assert ports.db == 25432
        assert ports.event_store == 60051
        assert ports.collector == 28080
        assert ports.minio == 29000
        assert ports.minio_console == 29001
        assert ports.redis == 26379
        assert ports.envoy == 28081

    def test_slot_3_ports(self) -> None:
        ports = em._compute_ports(3)
        assert ports.gateway == 38137
        assert ports.api == 39137
        assert ports.db == 35432
        assert ports.event_store == 61051
        assert ports.collector == 38080
        assert ports.redis == 36379

    def test_slot_5_max(self) -> None:
        ports = em._compute_ports(5)
        assert ports.gateway == 58137
        assert ports.api == 59137
        assert ports.event_store == 63051
        # Verify no port exceeds 65535
        for field_name in ports.__dataclass_fields__:
            port = getattr(ports, field_name)
            assert port <= 65535, f"{field_name}={port} exceeds max port"

    def test_slot_below_range_raises(self) -> None:
        with pytest.raises(ValueError, match="Slot must be 2-5"):
            em._compute_ports(1)

    def test_slot_above_range_raises(self) -> None:
        with pytest.raises(ValueError, match="Slot must be 2-5"):
            em._compute_ports(6)

    def test_event_store_separate_range(self) -> None:
        """Event store uses 60051 + (slot-2)*1000 to avoid exceeding 65535."""
        for slot in range(2, 6):
            ports = em._compute_ports(slot)
            expected = 60051 + (slot - 2) * 1000
            assert ports.event_store == expected

    def test_no_port_collisions_across_slots(self) -> None:
        """All ports across all slots must be unique."""
        all_ports: list[int] = []
        for slot in range(2, 6):
            ports = em._compute_ports(slot)
            for field_name in ports.__dataclass_fields__:
                all_ports.append(getattr(ports, field_name))
        assert len(all_ports) == len(set(all_ports)), "Port collision detected"


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class TestRegistry:
    def _make_env(self, name: str = "test", slot: int = 2) -> em.Environment:
        return em.Environment(
            name=name,
            branch=f"feat/{name}",
            slot=slot,
            created_at="2026-04-11T00:00:00+00:00",
            ports={"gateway": 28137, "api": 29137},
        )

    def test_find_existing(self) -> None:
        env = self._make_env("foo")
        registry = em.Registry(environments=[env])
        assert registry.find("foo") is env

    def test_find_missing_returns_none(self) -> None:
        registry = em.Registry(environments=[self._make_env("foo")])
        assert registry.find("bar") is None

    def test_used_slots(self) -> None:
        envs = [self._make_env("a", slot=2), self._make_env("b", slot=4)]
        registry = em.Registry(environments=envs)
        assert registry.used_slots() == {2, 4}

    def test_empty_registry(self) -> None:
        registry = em.Registry()
        assert registry.find("anything") is None
        assert registry.used_slots() == set()


class TestNextFreeSlot:
    def test_first_slot_is_2(self) -> None:
        registry = em.Registry()
        assert em._next_free_slot(registry) == 2

    def test_skips_used_slots(self) -> None:
        env = em.Environment(
            name="x", branch="x", slot=2,
            created_at="", ports={},
        )
        registry = em.Registry(environments=[env])
        assert em._next_free_slot(registry) == 3

    def test_finds_gap(self) -> None:
        envs = [
            em.Environment(name="a", branch="a", slot=2, created_at="", ports={}),
            em.Environment(name="b", branch="b", slot=4, created_at="", ports={}),
        ]
        registry = em.Registry(environments=envs)
        assert em._next_free_slot(registry) == 3

    def test_all_slots_full_raises(self) -> None:
        envs = [
            em.Environment(name=f"e{s}", branch=f"b{s}", slot=s, created_at="", ports={})
            for s in range(2, 6)
        ]
        registry = em.Registry(environments=envs)
        with pytest.raises(RuntimeError, match="All 4 on-demand slots are in use"):
            em._next_free_slot(registry)


# ---------------------------------------------------------------------------
# Registry serialization (round-trip through tmp_path)
# ---------------------------------------------------------------------------


class TestRegistrySerialization:
    def test_save_and_load_round_trip(self, tmp_path: Path) -> None:
        env = em.Environment(
            name="my-feature",
            branch="feat/my-feature",
            slot=3,
            created_at="2026-04-11T14:30:00+00:00",
            ports={"gateway": 38137, "api": 39137, "db": 35432},
        )
        registry = em.Registry(environments=[env])

        registry_file = tmp_path / "environments.json"
        with patch.object(em, "REGISTRY_FILE", registry_file):
            em._save_registry(registry)
            loaded = em._load_registry()

        assert len(loaded.environments) == 1
        loaded_env = loaded.environments[0]
        assert loaded_env.name == "my-feature"
        assert loaded_env.branch == "feat/my-feature"
        assert loaded_env.slot == 3
        assert loaded_env.ports["gateway"] == 38137

    def test_load_missing_file_returns_empty(self, tmp_path: Path) -> None:
        registry_file = tmp_path / "does-not-exist.json"
        with patch.object(em, "REGISTRY_FILE", registry_file):
            registry = em._load_registry()
        assert registry.environments == []

    def test_save_creates_parent_dirs(self, tmp_path: Path) -> None:
        registry_file = tmp_path / "nested" / "dir" / "environments.json"
        with patch.object(em, "REGISTRY_FILE", registry_file):
            em._save_registry(em.Registry())
        assert registry_file.exists()


# ---------------------------------------------------------------------------
# Env file generation
# ---------------------------------------------------------------------------


class TestWriteEnvFile:
    def test_writes_expected_content(self, tmp_path: Path) -> None:
        env = em.Environment(
            name="my-feature",
            branch="feat/my-feature",
            slot=2,
            created_at="2026-04-11T14:30:00+00:00",
            ports={
                "gateway": 28137, "api": 29137, "db": 25432,
                "event_store": 60051, "collector": 28080,
                "minio": 29000, "minio_console": 29001,
                "redis": 26379, "envoy": 28081,
            },
        )
        with patch.object(em, "REPO_ROOT", tmp_path):
            path = em._write_env_file(env)
            content = path.read_text()

        assert path.name == ".env.ondemand-my-feature"
        assert "SYN_ENV_NAME=my-feature" in content
        assert "SYN_ENV_PORT_GATEWAY=28137" in content
        assert "SYN_ENV_PORT_API=29137" in content
        assert "SYN_ENV_PORT_DB=25432" in content
        assert "SYN_ENV_PORT_ES=60051" in content
        assert "SYN_ENV_PORT_COLLECTOR=28080" in content
        assert "SYN_ENV_PORT_MINIO=29000" in content
        assert "SYN_ENV_PORT_MINIO_CONSOLE=29001" in content
        assert "SYN_ENV_PORT_REDIS=26379" in content
        assert "SYN_ENV_PORT_ENVOY=28081" in content
        assert "SYN_AGENT_NETWORK=syn-env-my-feature_agent-net" in content
        assert "DO NOT COMMIT" in content


# ---------------------------------------------------------------------------
# Compose argument construction
# ---------------------------------------------------------------------------


class TestComposeArgs:
    def test_builds_correct_args(self, tmp_path: Path) -> None:
        env = em.Environment(
            name="test-env",
            branch="feat/test",
            slot=2,
            created_at="",
            ports={},
        )
        with patch.object(em, "REPO_ROOT", tmp_path), \
             patch.object(em, "COMPOSE_BASE", tmp_path / "docker-compose.yaml"), \
             patch.object(em, "COMPOSE_ONDEMAND", tmp_path / "docker-compose.ondemand.yaml"):
            args = em._compose_args(env)

        assert args[0] == "docker"
        assert args[1] == "compose"
        assert "-f" in args
        assert "-p" in args
        idx = args.index("-p")
        assert args[idx + 1] == "syn-env-test-env"
        assert "--env-file" in args


# ---------------------------------------------------------------------------
# Env-to-dict (JSON output for agents)
# ---------------------------------------------------------------------------


class TestEnvToDict:
    def test_contains_all_urls(self) -> None:
        env = em.Environment(
            name="my-env",
            branch="feat/my-env",
            slot=2,
            created_at="2026-04-11T14:30:00+00:00",
            ports={
                "gateway": 28137, "api": 29137, "db": 25432,
                "event_store": 60051, "collector": 28080,
                "minio": 29000, "minio_console": 29001,
                "redis": 26379, "envoy": 28081,
            },
        )
        d = em._env_to_dict(env)

        assert d["name"] == "my-env"
        assert d["branch"] == "feat/my-env"
        assert d["url"] == "http://localhost:28137"
        assert d["api_url"] == "http://localhost:28137/api/v1"
        assert d["api_direct_url"] == "http://localhost:29137"
        assert d["api_docs_url"] == "http://localhost:28137/api/v1/docs"
        assert d["minio_console_url"] == "http://localhost:29001"
        assert d["agent_network"] == "syn-env-my-env_agent-net"
        assert d["ports"] == env.ports


# ---------------------------------------------------------------------------
# Allocate (integration of slug + slot + registry + env file)
# ---------------------------------------------------------------------------


class TestAllocate:
    def test_allocates_new_environment(self, tmp_path: Path) -> None:
        registry_file = tmp_path / "environments.json"
        with patch.object(em, "REGISTRY_FILE", registry_file), \
             patch.object(em, "REPO_ROOT", tmp_path):
            _, env = em._allocate("feat/cool-feature")

        assert env.name == "cool-feature"
        assert env.branch == "feat/cool-feature"
        assert env.slot == 2
        assert env.ports["gateway"] == 28137

        # Registry was saved
        data = json.loads(registry_file.read_text())
        assert len(data["environments"]) == 1

        # Env file was written
        env_file = tmp_path / ".env.ondemand-cool-feature"
        assert env_file.exists()

    def test_returns_existing_if_already_allocated(self, tmp_path: Path) -> None:
        registry_file = tmp_path / "environments.json"
        with patch.object(em, "REGISTRY_FILE", registry_file), \
             patch.object(em, "REPO_ROOT", tmp_path):
            _, env1 = em._allocate("feat/cool-feature")
            _, env2 = em._allocate("feat/cool-feature")

        assert env1.slot == env2.slot
        # Only one entry in registry
        data = json.loads(registry_file.read_text())
        assert len(data["environments"]) == 1

    def test_second_branch_gets_next_slot(self, tmp_path: Path) -> None:
        registry_file = tmp_path / "environments.json"
        with patch.object(em, "REGISTRY_FILE", registry_file), \
             patch.object(em, "REPO_ROOT", tmp_path):
            _, env1 = em._allocate("feat/first")
            _, env2 = em._allocate("feat/second")

        assert env1.slot == 2
        assert env2.slot == 3
        assert env1.ports["gateway"] != env2.ports["gateway"]
