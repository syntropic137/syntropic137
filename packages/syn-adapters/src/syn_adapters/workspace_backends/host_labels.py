"""Which host created this container? The labels that answer it.

Every container this API creates - workspace, sidecar, capture recovery helper -
is stamped with the host that created it (``syn.host_id``) and the build that
host was running (``syn.host_generation``), so a container can be attributed to
its creator from ``docker inspect`` alone (#1310, hot-upgrade plan item 0.4).
Every builder takes its labels from here, so none can disagree about what a
host is.

``syn.host_id`` must survive the API container being recreated - that is the
moment the next generation needs to find its predecessor's containers - and
must differ between hosts. ``SYN_HOST_ID`` wins when the deployment sets it;
otherwise it is the Docker engine ID from ``docker info``, which belongs to the
daemon and so has both properties. The API container's hostname has neither,
and is never used. If neither source answers, container creation fails rather
than stamping an identity that would not be recognised again.

``syn.host_generation`` is NOT configuration: it is the image tag stamped into
the image at build time (``SYN_BUILD_IMAGE_TAG``, see ``syn_api.build_info`` for
why that is read from the environment rather than from settings). An unstamped
build has no generation and says so with an empty value, never a placeholder
that could be mistaken for a real tag.
"""

from __future__ import annotations

import asyncio
import os

from syn_shared.settings import get_settings

LABEL_HOST_ID = "syn.host_id"
LABEL_HOST_GENERATION = "syn.host_generation"

#: Stamped by the image build; the same variable ``syn_api.build_info`` reads.
ENV_IMAGE_TAG = "SYN_BUILD_IMAGE_TAG"

_ENGINE_ID_TIMEOUT_SECONDS = 15

#: The engine ID cannot change under a running API, so it is asked for once.
_engine_id: str | None = None


class HostIdentityError(RuntimeError):
    """Neither ``SYN_HOST_ID`` nor the Docker engine could say which host this is."""


async def _query_engine_id() -> str:
    """The daemon's engine ID, or "" when Docker cannot be asked or will not say."""
    try:
        process = await asyncio.create_subprocess_exec(
            "docker",
            "info",
            "--format",
            "{{.ID}}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except OSError:
        return ""
    try:
        async with asyncio.timeout(_ENGINE_ID_TIMEOUT_SECONDS):
            stdout, _ = await process.communicate()
    except TimeoutError:
        return ""
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()
    return stdout.decode().strip() if process.returncode == 0 else ""


async def _docker_engine_id() -> str:
    global _engine_id
    if _engine_id is None:
        engine_id = await _query_engine_id()
        if not engine_id:
            raise HostIdentityError(
                "Cannot identify this Docker host for the syn.host_id label: "
                "`docker info` returned no engine ID. Set SYN_HOST_ID, or check "
                "that `docker info` succeeds for the API's Docker endpoint."
            )
        _engine_id = engine_id
    return _engine_id


async def host_labels() -> dict[str, str]:
    """Labels identifying the host creating a container, keyed by label name.

    Raises:
        HostIdentityError: SYN_HOST_ID is unset and the engine ID is unavailable.
    """
    return {
        LABEL_HOST_ID: get_settings().syn_host_id or await _docker_engine_id(),
        LABEL_HOST_GENERATION: os.environ.get(ENV_IMAGE_TAG, ""),
    }
