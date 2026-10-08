"""PC-130 B8: crossing the 15%-free threshold pages someone, once, and recovery says so.

Drives `DiskPager` over the real `DiskSpaceGuard` with the shipped default
thresholds; only the filesystem measurement and the webhook are doubles.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from syn_api.services.disk_pager import DiskPage, DiskPager, webhook_sender
from syn_domain.contexts._shared.disk_space import DiskSpaceGuard, DiskUsage
from syn_shared.settings.disk import DiskSettings

pytestmark = pytest.mark.unit


class _Disk:
    path = "/workspaces"

    def __init__(self) -> None:
        self.free_percent = 50.0

    def usage(self) -> DiskUsage:
        return DiskUsage(free_bytes=int(self.free_percent * 10), total_bytes=1000)


def _pager(disk: _Disk, sent: list[DiskPage], *, fail: list[bool] | None = None) -> DiskPager:
    settings = DiskSettings()
    guard = DiskSpaceGuard(
        disk,
        degraded_below_percent=settings.degraded_below_percent,
        refuse_admission_below_percent=settings.refuse_admission_below_percent,
    )

    async def send(page: DiskPage) -> None:
        if fail and fail[0]:
            raise OSError("webhook down")
        sent.append(page)

    return DiskPager(check=guard.check, send=send)


async def test_crossing_15_percent_pages_once_and_recovery_pages_once() -> None:
    disk, sent = _Disk(), []
    pager = _pager(disk, sent)
    await pager.run_once()
    assert sent == []
    disk.free_percent = 14.0
    await pager.run_once()
    await pager.run_once()
    disk.free_percent = 12.0
    await pager.run_once()
    assert [(p.previous_state, p.state, p.free_percent) for p in sent] == [("ok", "low", 14.0)]
    disk.free_percent = 4.0
    await pager.run_once()
    disk.free_percent = 40.0
    await pager.run_once()
    await pager.run_once()
    assert [(p.previous_state, p.state) for p in sent] == [
        ("ok", "low"),
        ("low", "critical"),
        ("critical", "ok"),
    ]


async def test_failed_delivery_is_retried_until_it_lands() -> None:
    disk, sent, fail = _Disk(), [], [True]
    pager = _pager(disk, sent, fail=fail)
    disk.free_percent = 10.0
    assert await pager.run_once() is None
    fail[0] = False
    page = await pager.run_once()
    assert page is not None and page.state == "low"
    assert len(sent) == 1


async def test_webhook_sender_posts_the_page_as_json() -> None:
    received: list[dict[str, object]] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            body = self.rfile.read(int(self.headers["Content-Length"]))
            received.append(json.loads(body))
            self.send_response(204)
            self.end_headers()

        def log_message(self, *_: object) -> None:
            return

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.handle_request, daemon=True)
    thread.start()
    try:
        page = DiskPage(
            state="low", previous_state="ok", path="/workspaces", free_percent=14.0, detail="d"
        )
        await webhook_sender(f"http://127.0.0.1:{server.server_port}/page")(page)
    finally:
        thread.join(timeout=5)
        server.server_close()
    assert received == [page.model_dump()]
