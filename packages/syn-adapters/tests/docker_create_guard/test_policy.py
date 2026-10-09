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
from agentic_isolation.config import codex_sandbox_seccomp_profile

from syn_adapters.docker_create_guard.__main__ import policy_from_env
from syn_adapters.docker_create_guard.policy import (
    _DEVICE_FIELDS,
    _HOST_NAMESPACE_FIELDS,
    _PROC_MASK_FIELDS,
    _UNCONFINED_SECURITY_OPTS,
    CreatePolicy,
    JsonObject,
    JsonValue,
    Refusal,
)
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


class FakeHost:
    """Every path exists; ``links`` maps a symlink path to the path it resolves to."""

    def __init__(
        self,
        images: dict[str, tuple[str, ...]] | None = None,
        links: dict[str, str] | None = None,
        missing: tuple[str, ...] = (),
    ) -> None:
        self._images = images or {}
        self._links = links or {}
        self._missing = missing

    def image_names(self, image_id: str) -> tuple[str, ...]:
        return self._images.get(image_id, ())

    def real_path(self, path: str) -> str | None:
        if path in self._missing:
            return None
        for link, target in self._links.items():
            if path == link or path.startswith(link + "/"):
                return target + path[len(link) :]
        return path


def _check(
    body: JsonObject, policy: CreatePolicy = POLICY, host: FakeHost | None = None
) -> Refusal | None:
    return policy.check(json.dumps(body).encode(), host or FakeHost())


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
        host = FakeHost(
            images={LOCAL_ID: ("ghcr.io/agentparadise/agentic-workspace-claude-cli:dev",)}
        )
        body = json.dumps(recovery_body()).encode()
        assert POLICY.check(body, host) is None

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
        refusal = POLICY.check(raw, FakeHost())
        assert refusal is not None and "more than once" in refusal.reason

    def test_bind_without_a_configured_root(self) -> None:
        refusal = _check(workspace_body(), CreatePolicy(workspace_root=None))
        assert refusal is not None and "SYN_WORKSPACE_HOST_DIR" in refusal.reason

    def test_symlink_inside_the_root_that_leaves_it(self) -> None:
        refusal = _check(workspace_body(), host=FakeHost(links={f"{ROOT}/ws-1": "/"}))
        assert refusal is not None and "resolves to '/'" in refusal.reason

    def test_symlinked_root_still_allows_its_own_paths(self) -> None:
        assert _check(workspace_body(), host=FakeHost(links={ROOT: "/data/ws"})) is None

    def test_bind_the_guard_cannot_see(self) -> None:
        refusal = _check(workspace_body(), host=FakeHost(missing=(f"{ROOT}/ws-1",)))
        assert refusal is not None and "cannot see" in refusal.reason

    def test_not_json(self) -> None:
        assert POLICY.check(b"{nope", FakeHost()) is not None


class TestEveryNamedShapeIsRefused:
    """Iterates the policy's own lists, so dropping any member fails the case named for it."""

    @pytest.mark.parametrize("name", _HOST_NAMESPACE_FIELDS)
    @pytest.mark.parametrize("mode", ["host", "container:syn137-docker-create-guard"])
    def test_namespace_join(self, name: str, mode: str) -> None:
        refusal = _check(_with(workspace_body(), **{name: mode}))
        assert refusal is not None and f"{name}={mode}" in refusal.reason

    @pytest.mark.parametrize("name", _DEVICE_FIELDS)
    def test_device_field(self, name: str) -> None:
        refusal = _check(_with(workspace_body(), **{name: ["c 1:3 rwm"]}))
        assert refusal is not None and name in refusal.reason

    @pytest.mark.parametrize("opt", sorted(_UNCONFINED_SECURITY_OPTS))
    def test_unconfined_security_opt(self, opt: str) -> None:
        refusal = _check(_with(workspace_body(), SecurityOpt=[opt]))
        assert refusal is not None and repr(opt) in refusal.reason

    @pytest.mark.parametrize("name", _PROC_MASK_FIELDS)
    def test_proc_masks(self, name: str) -> None:
        refusal = _check(_with(workspace_body(), **{name: []}))
        assert refusal is not None and name in refusal.reason

    def test_systempaths_unconfined_as_the_cli_sends_it(self) -> None:
        # docker/cli parseSystemPaths strips the option and sends both lists empty.
        assert _check(_with(workspace_body(), MaskedPaths=[], ReadonlyPaths=[])) is not None

    def test_volume_driver(self) -> None:
        refusal = _check(_with(workspace_body(), VolumeDriver="local"))
        assert refusal is not None and "VolumeDriver" in refusal.reason

    def test_root_configured_as_slash_allows_no_bind(self) -> None:
        refusal = _check(
            _with(workspace_body(), Binds=["/etc:/x"]), CreatePolicy(workspace_root="/")
        )
        assert refusal is not None and "only paths under" in refusal.reason


class TestSeccompProfile:
    @pytest.mark.parametrize("action", ["SCMP_ACT_ALLOW", "SCMP_ACT_LOG", "SCMP_ACT_TRACE"])
    def test_profile_that_does_not_deny_by_default(self, action: str) -> None:
        opt = "seccomp=" + json.dumps({"defaultAction": action})
        refusal = _check(_with(workspace_body(), SecurityOpt=[opt]))
        assert refusal is not None and action in refusal.reason

    @pytest.mark.parametrize("opt", ["seccomp={nope", "seccomp=[]", "seccomp:{}"])
    def test_unreadable_profile(self, opt: str) -> None:
        assert _check(_with(workspace_body(), SecurityOpt=[opt])) is not None

    def test_the_shipped_workspace_profile_passes(self) -> None:
        # What the CLI sends for --security-opt seccomp=<file>: the file's contents inline.
        opt = "seccomp=" + codex_sandbox_seccomp_profile().read_text()
        assert _check(_with(workspace_body(), SecurityOpt=["no-new-privileges", opt])) is None


class TestImageNames:
    @pytest.mark.parametrize("image", ["syn-sidecar-proxy-evil:latest", "syn-sidecar-proxy/x:1"])
    def test_exact_entry_has_a_boundary(self, image: str) -> None:
        refusal = _check(workspace_body(image))
        assert refusal is not None and "allowlist" in refusal.reason


class TestDeprecatedTopLevelHostConfig:
    @pytest.mark.parametrize(
        "fields",
        [{"Privileged": True}, {"Binds": ["/:/host"]}, {"PidMode": "host"}, {"CapAdd": ["ALL"]}],
    )
    def test_top_level_host_fields_are_checked(self, fields: JsonObject) -> None:
        body = sidecar_body()
        del body["HostConfig"]
        body.update(fields)
        assert _check(body) is not None
