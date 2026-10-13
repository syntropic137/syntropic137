"""HTTP front for the create policy, forwarding allowed creates to the Docker socket (#1806).

The socket proxy routes ``POST /containers/create`` and
``POST /containers/{id}/exec`` here and nothing else. A refused request gets a
403 whose ``message`` the docker CLI prints verbatim; an allowed one is
replayed against the daemon socket and its response returned.
"""

from __future__ import annotations

import http.client
import json
import logging
import os
import posixpath
import re
import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import TYPE_CHECKING, ClassVar
from urllib.parse import quote, unquote, urlsplit

from syn_adapters.docker_create_guard.policy import Refusal

if TYPE_CHECKING:
    from syn_adapters.docker_create_guard.policy import CreatePolicy, JsonObject

logger = logging.getLogger(__name__)

CREATE_PATH = re.compile(r"^(/v[0-9.]+)?/containers/create/*$", re.IGNORECASE)
EXEC_PATH = re.compile(r"^(/v[0-9.]+)?/containers/(.+?)/exec/*$", re.IGNORECASE)
_FORWARDED_RESPONSE_HEADERS = (
    "Content-Type",
    "Api-Version",
    "Docker-Experimental",
    "Ostype",
    "Server",
)
_MAX_BODY_BYTES = 4 * 1024 * 1024
# Sentinel from ``_check_exec``: the reply (a 502) is already sent.
_UNREACHABLE = Refusal("the exec target could not be inspected")


class _UnixHTTPConnection(http.client.HTTPConnection):
    def __init__(self, socket_path: str) -> None:
        super().__init__("localhost", timeout=60)
        self._socket_path = socket_path

    def connect(self) -> None:
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self._socket_path)


class DockerSocket:
    """The two daemon calls the guard makes: replay a create, and name a local image ID."""

    def __init__(self, socket_path: str) -> None:
        self._socket_path = socket_path

    def request(
        self, method: str, path: str, body: bytes | None, headers: dict[str, str]
    ) -> tuple[int, list[tuple[str, str]], bytes]:
        conn = _UnixHTTPConnection(self._socket_path)
        try:
            conn.request(method, path, body=body, headers=headers)
            response = conn.getresponse()
            return response.status, response.getheaders(), response.read()
        finally:
            conn.close()

    def image_names(self, image_id: str) -> tuple[str, ...]:
        status, _, body = self.request("GET", f"/images/{quote(image_id, safe=':')}/json", None, {})
        if status != 200:
            return ()
        document = json.loads(body)
        names = [*(document.get("RepoTags") or []), *(document.get("RepoDigests") or [])]
        return tuple(name for name in names if isinstance(name, str))

    def container(self, name_or_id: str) -> JsonObject | None:
        """The daemon's inspect of a container, or None when it does not know it."""
        status, _, body = self.request(
            "GET", f"/containers/{quote(name_or_id, safe='')}/json", None, {}
        )
        if status != 200:
            return None
        document = json.loads(body)
        return document if isinstance(document, dict) else None


class GuardHost:
    """The guard's view of the host: images from the daemon, paths from the read-only root mount.

    The workspaces root is mounted at ``mounted_root`` (the API's
    SYN_WORKSPACE_CONTAINER_DIR); host paths under ``host_root`` are resolved
    there and translated back, so a symlink resolves as the daemon would see it.
    """

    def __init__(
        self, docker: DockerSocket, host_root: str | None, mounted_root: str | None
    ) -> None:
        self._docker = docker
        self._host_root = posixpath.normpath(host_root) if host_root else None
        self._mounted_root = posixpath.normpath(mounted_root) if mounted_root else None

    @property
    def docker(self) -> DockerSocket:
        return self._docker

    def image_names(self, image_id: str) -> tuple[str, ...]:
        return self._docker.image_names(image_id)

    def real_path(self, path: str) -> str | None:
        host_root, mounted_root = self._host_root, self._mounted_root
        if host_root is None or mounted_root is None:
            return None
        if path != host_root and not path.startswith(host_root + "/"):
            return None
        local = mounted_root + path[len(host_root) :]
        if not os.path.lexists(local):
            return None
        real = os.path.realpath(local)
        if real == mounted_root or real.startswith(mounted_root + "/"):
            return host_root + real[len(mounted_root) :]
        return real


class CreateGuardHandler(BaseHTTPRequestHandler):
    """Checks one create body against ``policy``; ``make_handler`` binds policy and host."""

    protocol_version = "HTTP/1.1"
    policy: ClassVar[CreatePolicy]
    host: ClassVar[GuardHost]

    def do_POST(self) -> None:
        path = unquote(urlsplit(self.path).path)
        exec_target = EXEC_PATH.match(path)
        if not CREATE_PATH.match(path) and exec_target is None:
            self._reply(
                403, f"the create guard only serves container create and exec, not {self.path!r}"
            )
            return
        body = self._read_body()
        if body is None:
            return
        if exec_target is None:
            refusal = self.policy.check(body, self.host)
        else:
            refusal = self._check_exec(body, exec_target.group(2))
            if refusal is _UNREACHABLE:
                return
        if refusal is not None:
            logger.warning("refused %s: %s", self.path, refusal.reason)
            self._reply(
                403, f"refused by the Syntropic137 container-create guard: {refusal.reason}"
            )
            return
        self._forward(body)

    def _read_body(self) -> bytes | None:
        length = self.headers.get("Content-Length")
        if length is None or not length.isdigit() or int(length) > _MAX_BODY_BYTES:
            self._reply(411, "container create and exec need a Content-Length under 4 MiB")
            return None
        return self.rfile.read(int(length))

    def _check_exec(self, body: bytes, target_name: str) -> Refusal | None:
        """The exec refusal, or ``_UNREACHABLE`` once a 502 has been sent."""
        try:
            target = self.host.docker.container(target_name)
        except (OSError, ValueError) as exc:
            logger.error("exec target could not be inspected: %s", exc)
            self._reply(502, f"the create guard could not inspect the exec target: {exc}")
            return _UNREACHABLE
        return self.policy.check_exec(body, target, self.host)

    def _forward(self, body: bytes) -> None:
        headers = {"Content-Type": self.headers.get("Content-Type", "application/json")}
        try:
            status, response_headers, response_body = self.host.docker.request(
                "POST", self.path, body, headers
            )
        except OSError as exc:
            logger.error("container create could not reach the Docker socket: %s", exc)
            self._reply(502, f"the create guard could not reach the Docker daemon: {exc}")
            return
        self.send_response(status)
        for name, value in response_headers:
            if name.title() in _FORWARDED_RESPONSE_HEADERS:
                self.send_header(name, value)
        self.send_header("Content-Length", str(len(response_body)))
        self.end_headers()
        self.wfile.write(response_body)

    def _reply(self, status: int, message: str) -> None:
        payload = json.dumps({"message": message}).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args: object) -> None:
        logger.debug(format, *args)


def make_handler(policy: CreatePolicy, host: GuardHost) -> type[CreateGuardHandler]:
    return type("BoundCreateGuardHandler", (CreateGuardHandler,), {"policy": policy, "host": host})


def serve(policy: CreatePolicy, host: GuardHost, port: int) -> None:
    server = ThreadingHTTPServer(("0.0.0.0", port), make_handler(policy, host))
    logger.info("container-create guard listening on :%d", port)
    server.serve_forever()
