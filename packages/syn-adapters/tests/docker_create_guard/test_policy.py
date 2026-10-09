"""The container-create policy (#1806): the platform's own shapes pass, host access is refused.

The allowed bodies are the ``POST /containers/create`` payloads the docker CLI
sends for each create path the API has, with images taken from the platform's
real defaults, so moving a default image outside the allowlist fails here
before it fails a provision.
"""

from __future__ import annotations

import copy
import json

import pytest

from syn_adapters.docker_create_guard.__main__ import policy_from_env
from syn_adapters.docker_create_guard.policy import CreatePolicy, JsonObject, JsonValue, Refusal
from syn_adapters.workspace_backends.docker.docker_sidecar_adapter import DEFAULT_SIDECAR_IMAGE
from syn_shared.settings.workspace_images import (
    DEFAULT_WORKSPACE_IMAGE,
    WorkspaceImageProvider,
    workspace_image_ref,
)

pytestmark = pytest.mark.unit

ROOT = "/srv/syn137/workspaces"
POLICY = CreatePolicy(workspace_root=ROOT)
LOCAL_ID = "sha256:" + "c" * 64
CAPTURE = "syn-capture-" + "ab" * 32


def _no_local_images(_: str) -> tuple[str, ...]:
    return ()


def _check(body: JsonObject, policy: CreatePolicy = POLICY) -> Refusal | None:
    return policy.check(json.dumps(body).encode(), _no_local_images)


def workspace_body(image: str = DEFAULT_WORKSPACE_IMAGE) -> JsonObject:
    """agentic_isolation DockerProvider._build_run_command + SecurityConfig.to_docker_run_args."""
    return {
        "Image": image,
        "WorkingDir": "/workspace",
        "Env": ["WORKSPACE_ID=ws-1"],
        "Labels": {"syn.host_id": "api", "syn.workspace_id": "ws-1"},
        "HostConfig": {
            "NetworkMode": "agent-net",
            "Binds": [f"{ROOT}/ws-1:/workspace:rw"],
            "Mounts": [{"Type": "volume", "Source": CAPTURE, "Target": "/spool"}],
            "CapDrop": ["ALL"],
            "SecurityOpt": [
                "no-new-privileges",
                'seccomp={"defaultAction":"SCMP_ACT_ERRNO"}',
                "apparmor=syn-workspace",
            ],
            "ReadonlyRootfs": True,
            "Tmpfs": {"/tmp": "rw,noexec,nosuid,size=512m", "/home/agent": "rw,size=256m"},
            "PidsLimit": 256,
            "Memory": 4294967296,
            "NanoCpus": 2000000000,
            "Runtime": "runsc",
            "Privileged": False,
        },
        "NetworkingConfig": {"EndpointsConfig": {"agent-net": {}}},
    }


def sidecar_body() -> JsonObject:
    """docker_sidecar_helpers.build_sidecar_run_command."""
    return {
        "Image": DEFAULT_SIDECAR_IMAGE,
        "Env": ["UPSTREAM=api"],
        "Labels": {"syn.sidecar": "true"},
        "HostConfig": {
            "NetworkMode": "agent-net",
            "AutoRemove": True,
            "Memory": 134217728,
            "NanoCpus": 250000000,
        },
    }


def recovery_body(image: str = LOCAL_ID) -> JsonObject:
    """session_inventory.docker_recovery: the image may be a verified local image ID."""
    return {
        "Image": image,
        "User": "1000",
        "HostConfig": {
            "NetworkMode": "none",
            "ReadonlyRootfs": True,
            "CapDrop": ["ALL"],
            "SecurityOpt": ["no-new-privileges"],
            "Tmpfs": {"/tmp": ""},
            "Mounts": [{"Type": "volume", "Source": CAPTURE, "Target": "/spool"}],
        },
    }


def _with(body: JsonObject, **host_config: JsonValue) -> JsonObject:
    changed = copy.deepcopy(body)
    hc = changed["HostConfig"]
    assert isinstance(hc, dict)
    hc.update(host_config)
    return changed


class TestPlatformShapesPass:
    def test_workspace(self) -> None:
        assert _check(workspace_body()) is None

    @pytest.mark.parametrize("provider", list(WorkspaceImageProvider))
    def test_every_pinned_workspace_image(self, provider: WorkspaceImageProvider) -> None:
        assert _check(workspace_body(workspace_image_ref(provider))) is None

    def test_sidecar(self) -> None:
        assert _check(sidecar_body()) is None

    def test_recovery_with_a_local_image_id_named_by_an_allowed_tag(self) -> None:
        names = {LOCAL_ID: ("ghcr.io/agentparadise/agentic-workspace-claude-cli:dev",)}
        body = json.dumps(recovery_body()).encode()
        assert POLICY.check(body, lambda ref: names.get(ref, ())) is None

    def test_operator_pinned_image_is_allowed_from_env(self) -> None:
        policy = policy_from_env(
            {
                "SYN_WORKSPACE_HOST_DIR": ROOT,
                "SYN_WORKSPACE_DOCKER_IMAGE": "registry.corp/ws:1@sha256:" + "d" * 64,
            }
        )
        assert _check(workspace_body("registry.corp/ws:2"), policy) is None
        assert _check(workspace_body("registry.corp/other:1"), policy) is not None

    def test_extra_prefixes_from_env(self) -> None:
        policy = policy_from_env(
            {
                "SYN_WORKSPACE_HOST_DIR": ROOT,
                "SYN_DOCKER_CREATE_GUARD_IMAGE_PREFIXES": "a.io/x/, b.io/y",
            }
        )
        assert _check(workspace_body("b.io/y:1"), policy) is None


class TestHostAccessIsRefused:
    @pytest.mark.parametrize(
        ("host_config", "reason"),
        [
            ({"Privileged": True}, "privileged"),
            ({"CapAdd": ["SYS_ADMIN"]}, "CapAdd"),
            ({"NetworkMode": "host"}, "NetworkMode=host"),
            ({"PidMode": "host"}, "PidMode=host"),
            ({"IpcMode": "host"}, "IpcMode=host"),
            ({"UsernsMode": "host"}, "UsernsMode=host"),
            ({"Devices": [{"PathOnHost": "/dev/sda", "PathInContainer": "/dev/sda"}]}, "Devices"),
            ({"DeviceRequests": [{"Count": -1, "Capabilities": [["gpu"]]}]}, "DeviceRequests"),
            ({"Binds": ["/:/host"]}, "'/'"),
            ({"Binds": ["/var/run/docker.sock:/var/run/docker.sock"]}, "docker.sock"),
            ({"Binds": [f"{ROOT}/../../etc:/etc2"]}, "'..'"),
            ({"Binds": [f"{ROOT}:/all"]}, "only paths under"),
            ({"Binds": [f"{ROOT}-evil/x:/x"]}, "only paths under"),
            ({"Binds": ["syn137_postgres-data:/db"]}, "volume 'syn137_postgres-data'"),
            ({"Mounts": [{"Type": "bind", "Source": "/", "Target": "/host"}]}, "'/'"),
            (
                {"Mounts": [{"Type": "bind", "Source": "/var/run/docker.sock", "Target": "/s"}]},
                "docker.sock",
            ),
            (
                {
                    "Mounts": [
                        {
                            "Type": "volume",
                            "Source": CAPTURE,
                            "Target": "/s",
                            "VolumeOptions": {
                                "DriverConfig": {
                                    "Name": "local",
                                    "Options": {"o": "bind", "device": "/"},
                                }
                            },
                        }
                    ]
                },
                "DriverConfig",
            ),
            (
                {"Mounts": [{"Type": "image", "Source": "alpine", "Target": "/i"}]},
                "mount type 'image'",
            ),
            ({"VolumesFrom": ["syn137-docker-socket-proxy"]}, "VolumesFrom"),
            ({"SecurityOpt": ["seccomp=unconfined"]}, "seccomp=unconfined"),
        ],
    )
    def test_refused(self, host_config: JsonObject, reason: str) -> None:
        refusal = _check(_with(workspace_body(), **host_config))
        assert refusal is not None and reason in refusal.reason

    def test_host_network_by_endpoint(self) -> None:
        body = workspace_body()
        body["NetworkingConfig"] = {"EndpointsConfig": {"host": {}}}
        assert _check(body) is not None

    @pytest.mark.parametrize(
        "image", ["alpine", "docker:cli", "ghcr.io/evil/agentic-workspace-x", "syn-api"]
    )
    def test_foreign_image(self, image: str) -> None:
        refusal = _check(workspace_body(image))
        assert refusal is not None and "allowlist" in refusal.reason

    def test_unknown_local_image_id(self) -> None:
        assert _check(recovery_body()) is not None

    def test_field_names_fold_like_go(self) -> None:
        body: JsonObject = {"image": DEFAULT_WORKSPACE_IMAGE, "hostconfig": {"PRIVILEGED": True}}
        assert _check(body) is not None
        # U+017F LONG S folds to s in Go's EqualFold, so this still decodes as HostConfig.
        body = {"Image": DEFAULT_WORKSPACE_IMAGE, "Ho\u017ftConfig": {"Privileged": True}}
        assert _check(body) is not None

    def test_ambiguous_duplicate_field_is_refused(self) -> None:
        image = json.dumps(DEFAULT_WORKSPACE_IMAGE)
        raw = f'{{"Image": {image}, "HostConfig": {{"Privileged": false, "privileged": true}}}}'.encode()
        refusal = POLICY.check(raw, _no_local_images)
        assert refusal is not None and "more than once" in refusal.reason

    def test_bind_without_a_configured_root(self) -> None:
        refusal = _check(workspace_body(), CreatePolicy(workspace_root=None))
        assert refusal is not None and "SYN_WORKSPACE_HOST_DIR" in refusal.reason

    def test_not_json(self) -> None:
        assert POLICY.check(b"{nope", _no_local_images) is not None
