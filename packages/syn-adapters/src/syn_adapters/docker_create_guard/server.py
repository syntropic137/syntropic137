"""HTTP front for the create policy, forwarding allowed creates to the Docker socket (#1806).

The socket proxy routes ``POST /containers/create`` here and nothing else. A
refused create gets a 403 whose ``message`` the docker CLI prints verbatim; an
allowed one is replayed against the daemon socket and its response returned.
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

if TYPE_CHECKING:
    from syn_adapters.docker_create_guard.policy import CreatePolicy

logger = logging.getLogger(__name__)

CREATE_PATH = re.compile(r"^(/v[0-9.]+)?/containers/create/*$", re.IGNORECASE)
_FORWARDED_RESPONSE_HEADERS = (
    "Content-Type",
    "Api-Version",
    "Docker-Experimental",
    "Ostype",
    "Server",
)
_MAX_BODY_BYTES = 4 * 1024 * 1024


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
        if not CREATE_PATH.match(unquote(urlsplit(self.path).path)):
            self._reply(403, f"the create guard only serves container create, not {self.path!r}")
            return
        length = self.headers.get("Content-Length")
        if length is None or not length.isdigit() or int(length) > _MAX_BODY_BYTES:
            self._reply(411, "container create needs a Content-Length under 4 MiB")
            return
        body = self.rfile.read(int(length))
        refusal = self.policy.check(body, self.host)
        if refusal is not None:
            logger.warning("refused container create: %s", refusal.reason)
            self._reply(
                403, f"refused by the Syntropic137 container-create guard: {refusal.reason}"
            )
            return
        self._forward(body)

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
