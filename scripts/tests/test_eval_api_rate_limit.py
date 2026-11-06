"""The eval scripts wait out an API 429 instead of dying mid-run.

A shared deployment rate-limits; before this, `migrate_eval_suite_duplicates.py
--dry-run` and `eval_suite.py launch` failed partway on the first 429.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from typing import TYPE_CHECKING

from eval_suite import RATE_LIMIT_MAX_WAIT_SECONDS, RateLimitRetry, api_client

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = pytest.mark.unit


def _server(
    statuses: list[int], headers: dict[str, str] | None = None
) -> tuple[httpx.MockTransport, list[str]]:
    seen: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request.method)
        status = statuses[min(len(seen) - 1, len(statuses) - 1)]
        return httpx.Response(
            status, headers=headers if status == 429 else None, json={"n": len(seen)}
        )

    return httpx.MockTransport(handle), seen


def _client(transport: httpx.MockTransport, waits: list[float], attempts: int = 6) -> httpx.Client:
    return httpx.Client(
        base_url="http://api.test",
        transport=RateLimitRetry(transport, attempts=attempts, sleep=waits.append),
    )


def test_a_429_is_retried_until_the_api_answers() -> None:
    transport, _ = _server([429, 429, 200])
    waits: list[float] = []
    with _client(transport, waits) as client:
        response = client.get("/evals")
    assert response.status_code == 200
    assert response.json() == {"n": 3}
    assert waits == [2.0, 4.0], "no Retry-After: a doubling wait"


def test_a_post_is_retried_too_because_a_429_was_not_acted_on() -> None:
    transport, seen = _server([429, 201])
    waits: list[float] = []
    with _client(transport, waits) as client:
        assert client.post("/evals", json={}).status_code == 201
    assert seen == ["POST", "POST"]


def test_retry_after_is_honoured_and_capped() -> None:
    transport, _ = _server([429, 429, 200], headers={"retry-after": "7"})
    waits: list[float] = []
    with _client(transport, waits) as client:
        client.get("/evals")
    assert waits == [7.0, 7.0]

    transport, _ = _server([429, 200], headers={"retry-after": "9999"})
    waits = []
    with _client(transport, waits) as client:
        client.get("/evals")
    assert waits == [RATE_LIMIT_MAX_WAIT_SECONDS]


def test_the_last_429_is_returned_when_attempts_run_out() -> None:
    transport, seen = _server([429])
    waits: list[float] = []
    with _client(transport, waits, attempts=3) as client:
        response = client.get("/evals")
    assert response.status_code == 429
    assert len(seen) == 3
    assert len(waits) == 2


@pytest.mark.parametrize("status", [200, 404, 500, 503])
def test_any_other_status_is_returned_as_it_came(status: int) -> None:
    transport, seen = _server([status])
    waits: list[float] = []
    with _client(transport, waits) as client:
        assert client.get("/evals").status_code == status
    assert len(seen) == 1
    assert waits == []


def test_every_eval_script_builds_its_client_through_api_client() -> None:
    scripts = Path(__file__).resolve().parents[1]
    for name in ("eval_suite.py", "migrate_eval_suite_duplicates.py", "eval_judge_calibrate.py"):
        text = (scripts / name).read_text(encoding="utf-8")
        assert "with api_client(args.api_url) as client" in text, name
    with api_client("http://api.test") as client:
        assert isinstance(client._transport, RateLimitRetry)  # pyright: ignore[reportPrivateUsage]


def test_an_http_date_retry_after_waits_until_that_time() -> None:
    now = datetime(2026, 11, 6, 12, 0, 0, tzinfo=UTC)
    transport, _ = _server([429, 200], headers={"retry-after": "Fri, 06 Nov 2026 12:00:45 GMT"})
    waits: list[float] = []
    with httpx.Client(
        base_url="http://api.test",
        transport=RateLimitRetry(transport, sleep=waits.append, now=lambda: now),
    ) as client:
        assert client.get("/evals").status_code == 200
    assert waits == [45.0]


def test_a_date_in_the_past_retries_at_once() -> None:
    now = datetime(2026, 11, 6, 12, 0, 0, tzinfo=UTC)
    transport, _ = _server([429, 200], headers={"retry-after": "Fri, 06 Nov 2026 11:00:00 GMT"})
    waits: list[float] = []
    with httpx.Client(
        base_url="http://api.test",
        transport=RateLimitRetry(transport, sleep=waits.append, now=lambda: now),
    ) as client:
        client.get("/evals")
    assert waits == [0.0]


class _BrokenBody(httpx.SyncByteStream):
    """A 429 body that fails if anyone reads it, and records that it was closed."""

    closed = False

    def __iter__(self) -> Iterator[bytes]:
        raise httpx.ReadError("connection dropped mid-body")

    def close(self) -> None:
        _BrokenBody.closed = True


def test_a_429_whose_body_cannot_be_read_is_closed_and_retried() -> None:
    calls: list[int] = []

    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(429, stream=_BrokenBody())
        return httpx.Response(200, json={})

    waits: list[float] = []
    with _client(httpx.MockTransport(handle), waits) as client:
        assert client.get("/evals").status_code == 200
    assert _BrokenBody.closed
    assert len(calls) == 2


def test_the_referee_builds_its_client_through_api_client() -> None:
    text = (Path(__file__).resolve().parents[1] / "eval_referee.py").read_text(encoding="utf-8")
    assert "with api_client(args.api_url) as client" in text
    assert "httpx.Client(" not in text


def test_api_client_keeps_the_environment_proxy_and_retries_through_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.test:3128")
    monkeypatch.setenv("HTTP_PROXY", "http://proxy.test:3128")
    monkeypatch.setenv("NO_PROXY", "internal.test")
    with api_client("http://api.test") as client:
        mounts = client._mounts  # pyright: ignore[reportPrivateUsage]
        proxied = [t for t in mounts.values() if t is not None]
        assert proxied, "the environment proxy must still be mounted"
        assert all(isinstance(t, RateLimitRetry) for t in proxied)
        assert None in mounts.values(), "NO_PROXY must still bypass the proxy"
