"""Run the container-create guard: ``python -m syn_adapters.docker_create_guard``.

Environment:
    SYN_WORKSPACE_HOST_DIR: host path workspace bind mounts must sit under.
    SYN_WORKSPACE_CONTAINER_DIR: where that root is mounted (read-only) in the guard.
    SYN_WORKSPACE_DOCKER_IMAGE: an operator-pinned workspace image, allowed too.
    SYN_DOCKER_CREATE_GUARD_IMAGE_PREFIXES: extra comma-separated image repository prefixes.
    SYN_DOCKER_CREATE_GUARD_PORT: listen port (default 2375).
    SYN_DOCKER_CREATE_GUARD_SOCKET: daemon socket (default /var/run/docker.sock).
"""

from __future__ import annotations

import logging
import os

from syn_adapters.docker_create_guard.policy import (
    DEFAULT_IMAGE_PREFIXES,
    CreatePolicy,
    image_repository,
)
from syn_adapters.docker_create_guard.server import DockerSocket, GuardHost, serve


def policy_from_env(env: dict[str, str]) -> CreatePolicy:
    extra = [p.strip() for p in env.get("SYN_DOCKER_CREATE_GUARD_IMAGE_PREFIXES", "").split(",")]
    pinned = env.get("SYN_WORKSPACE_DOCKER_IMAGE", "").strip()
    if pinned:
        extra.append(image_repository(pinned))
    return CreatePolicy(
        workspace_root=env.get("SYN_WORKSPACE_HOST_DIR") or None,
        image_prefixes=DEFAULT_IMAGE_PREFIXES + tuple(p for p in extra if p),
    )


def main() -> None:
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
    env = dict(os.environ)
    serve(
        policy_from_env(env),
        GuardHost(
            DockerSocket(env.get("SYN_DOCKER_CREATE_GUARD_SOCKET", "/var/run/docker.sock")),
            host_root=env.get("SYN_WORKSPACE_HOST_DIR") or None,
            mounted_root=env.get("SYN_WORKSPACE_CONTAINER_DIR") or None,
        ),
        int(env.get("SYN_DOCKER_CREATE_GUARD_PORT", "2375")),
    )


if __name__ == "__main__":
    main()
