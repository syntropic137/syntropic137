"""What a container the API creates may ask the Docker daemon for (#1806).

The socket proxy filters on method and path only, so ``POST /containers/create``
reaches the daemon whatever its HostConfig says. This policy reads the body and
refuses the shapes that hand a container the host: privilege, added
capabilities, host namespaces, devices, host paths outside the workspaces root,
other containers' volumes, and images the platform does not run.

It is an allowlist of what the platform's own create paths send today:

| Path | Image | HostConfig |
|---|---|---|
| workspace (agentic_isolation DockerProvider) | ``ghcr.io/agentparadise/agentic-workspace-*`` or ``SYN_WORKSPACE_DOCKER_IMAGE`` | cap-drop ALL, no-new-privileges, named seccomp/apparmor, optional ``runsc``, bind ``<workspaces root>/...:/workspace``, ``syn-capture-*`` volumes, tmpfs |
| sidecar proxy (docker_sidecar_helpers) | ``syn-sidecar-proxy`` | network, memory, cpus |
| capture recovery (docker_recovery) | the workspace image, possibly as a local image ID | network none, cap-drop ALL, ``syn-capture-*`` volume, tmpfs |

Anything else passes untouched: the policy refuses named shapes, it does not
enumerate every field. To let a new shape through, extend the allowlist here
and pin it in ``tests/docker_create_guard/test_policy.py``. To let an operator
image through, set ``SYN_DOCKER_CREATE_GUARD_IMAGE_PREFIXES``.

Field names are matched case-insensitively, as the daemon's Go JSON decoder
does, and an object naming one field twice under different cases is refused
rather than guessed at.
"""

from __future__ import annotations

import json
import posixpath
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import NoReturn

type JsonValue = str | int | float | bool | None | list[JsonValue] | dict[str, JsonValue]
"""A decoded JSON value. The create body is checked field by field, not modelled:
the daemon decodes it case-insensitively, which a model would not reproduce."""
type JsonObject = dict[str, JsonValue]

DEFAULT_IMAGE_PREFIXES: tuple[str, ...] = (
    "ghcr.io/agentparadise/agentic-workspace-",
    "ghcr.io/syntropic137/",
    "syn-sidecar-proxy",
)
DEFAULT_VOLUME_PREFIXES: tuple[str, ...] = ("syn-capture-",)

_HOST_NAMESPACE_FIELDS = (
    "NetworkMode",
    "PidMode",
    "IpcMode",
    "UTSMode",
    "UsernsMode",
    "CgroupnsMode",
)
_DEVICE_FIELDS = ("Devices", "DeviceRequests", "DeviceCgroupRules")
_UNCONFINED_SECURITY_OPTS = frozenset(
    {
        "seccomp=unconfined",
        "seccomp:unconfined",
        "apparmor=unconfined",
        "apparmor:unconfined",
        "label=disable",
        "label:disable",
        "systempaths=unconfined",
    }
)


@dataclass(frozen=True)
class Refusal:
    """Why a create request was refused, phrased for the operator reading the CLI error."""

    reason: str


class _Refused(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


ImageNames = Callable[[str], tuple[str, ...]]
"""Resolve a local image ID to its repo tags and digests (empty when unknown)."""


@dataclass(frozen=True)
class CreatePolicy:
    """The container-create allowlist. ``workspace_root`` is the HOST path workspaces live under."""

    workspace_root: str | None
    image_prefixes: tuple[str, ...] = DEFAULT_IMAGE_PREFIXES
    volume_prefixes: tuple[str, ...] = DEFAULT_VOLUME_PREFIXES

    def check(self, body: bytes, image_names: ImageNames) -> Refusal | None:
        """Return why ``body`` (a ``POST /containers/create`` payload) is refused, or None."""
        try:
            request = json.loads(body)
            if not isinstance(request, dict):
                _refuse("the create body is not a JSON object")
            self._check_image(_field(request, "Image"), image_names)
            host_config = _field(request, "HostConfig")
            if host_config is not None:
                if not isinstance(host_config, dict):
                    _refuse("HostConfig is not an object")
                self._check_host_config(host_config)
            self._check_endpoints(_field(request, "NetworkingConfig"))
        except _Refused as refused:
            return Refusal(refused.reason)
        except ValueError as exc:
            return Refusal(f"the create body is not valid JSON ({exc})")
        return None

    def _check_image(self, image: object, image_names: ImageNames) -> None:
        if not isinstance(image, str) or image == "":
            _refuse("the create request names no image")
        candidates = image_names(image) if _is_image_id(image) else (image,)
        if not any(self._image_allowed(name) for name in candidates):
            _refuse(
                f"image {image!r} is not in the allowlist {list(self.image_prefixes)}; "
                "add its repository to SYN_DOCKER_CREATE_GUARD_IMAGE_PREFIXES"
            )

    def _image_allowed(self, image: str) -> bool:
        repository = image_repository(image)
        return any(repository.startswith(prefix) for prefix in self.image_prefixes)

    def _check_host_config(self, host_config: Mapping[str, JsonValue]) -> None:
        _expect(
            _field(host_config, "Privileged") in (None, False), "privileged containers are refused"
        )
        _expect(
            not _field(host_config, "CapAdd"),
            "CapAdd is refused: no platform container adds capabilities",
        )
        for name in _HOST_NAMESPACE_FIELDS:
            mode = _field(host_config, name)
            _expect(
                not (isinstance(mode, str) and mode.lower() == "host"), f"{name}=host is refused"
            )
        for name in _DEVICE_FIELDS:
            _expect(
                not _field(host_config, name),
                f"{name} is refused: no platform container maps devices",
            )
        _expect(not _field(host_config, "VolumesFrom"), "VolumesFrom is refused")
        _expect(not _field(host_config, "VolumeDriver"), "VolumeDriver is refused")
        for opt in _list(host_config, "SecurityOpt"):
            _expect(
                not (isinstance(opt, str) and opt.lower() in _UNCONFINED_SECURITY_OPTS),
                f"SecurityOpt {opt!r} is refused",
            )
        for bind in _list(host_config, "Binds"):
            if not isinstance(bind, str):
                _refuse("a Binds entry is not a string")
            source = bind.split(":", 1)[0]
            if source.startswith("/"):
                self._check_host_path(source)
            else:
                self._check_volume_name(source)
        for mount in _list(host_config, "Mounts"):
            if not isinstance(mount, dict):
                _refuse("a Mounts entry is not an object")
            self._check_mount(mount)

    def _check_mount(self, mount: Mapping[str, JsonValue]) -> None:
        kind = _field(mount, "Type")
        source = _field(mount, "Source")
        if kind == "bind":
            if not isinstance(source, str):
                _refuse("a bind mount has no source")
            self._check_host_path(source)
        elif kind == "volume":
            options = _field(mount, "VolumeOptions")
            if options is not None:
                if not isinstance(options, dict):
                    _refuse("VolumeOptions is not an object")
                _expect(not _field(options, "DriverConfig"), "a volume DriverConfig is refused")
            if source not in (None, ""):
                if not isinstance(source, str):
                    _refuse("a volume mount source is not a string")
                self._check_volume_name(source)
        else:
            _expect(kind == "tmpfs", f"mount type {kind!r} is refused")

    def _check_host_path(self, source: str) -> None:
        root = self.workspace_root
        if root is None:
            _refuse(
                f"bind mount of {source!r} is refused: SYN_WORKSPACE_HOST_DIR is not set for the guard"
            )
        normal_root = posixpath.normpath(root)
        _expect(".." not in source.split("/"), f"bind mount source {source!r} contains '..'")
        normal = posixpath.normpath(source)
        _expect(
            normal_root != "/" and normal.startswith(normal_root + "/"),
            f"bind mount of {source!r} is refused: only paths under {normal_root}/ may be bound",
        )

    def _check_volume_name(self, name: str) -> None:
        _expect(
            any(name.startswith(prefix) for prefix in self.volume_prefixes),
            f"volume {name!r} is refused: only {list(self.volume_prefixes)} volumes may be mounted",
        )

    def _check_endpoints(self, networking: object) -> None:
        if not isinstance(networking, dict):
            return
        endpoints = _field(networking, "EndpointsConfig")
        if isinstance(endpoints, dict):
            _expect(
                "host" not in {str(name).lower() for name in endpoints},
                "the host network is refused",
            )


def _field(obj: Mapping[str, JsonValue], name: str) -> JsonValue:
    """Read ``name`` the way Go's encoding/json does: case-insensitively."""
    folded = name.casefold()
    matches = [key for key in obj if key.casefold() == folded]
    _expect(len(matches) <= 1, f"{name} is given more than once ({matches})")
    return obj[matches[0]] if matches else None


def _list(obj: Mapping[str, JsonValue], name: str) -> list[JsonValue]:
    value = _field(obj, name)
    if value is None:
        return []
    if not isinstance(value, list):
        _refuse(f"{name} is not a list")
    return list(value)


def image_repository(image: str) -> str:
    """The repository part of an image reference: no tag, no digest."""
    name = image.split("@", 1)[0]
    colon = name.rfind(":")
    return name[:colon] if colon > name.rfind("/") else name


def _is_image_id(image: str) -> bool:
    """A local image ID, as image verification returns for a permitted local image."""
    return re.fullmatch(r"(sha256:)?[a-f0-9]{64}", image) is not None


def _expect(condition: bool, reason: str) -> None:
    if not condition:
        raise _Refused(reason)


def _refuse(reason: str) -> NoReturn:
    raise _Refused(reason)
