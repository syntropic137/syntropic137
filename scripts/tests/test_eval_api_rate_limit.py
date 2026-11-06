"""The eval scripts wait out an API 429 instead of dying mid-run.

A shared deployment rate-limits; before this, `migrate_eval_suite_duplicates.py
--dry-run` and `eval_suite.py launch` failed partway on the first 429.
"""

from __future__ import annotations

import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eval_suite import RATE_LIMIT_MAX_WAIT_SECONDS, RateLimitRetry, api_client

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
