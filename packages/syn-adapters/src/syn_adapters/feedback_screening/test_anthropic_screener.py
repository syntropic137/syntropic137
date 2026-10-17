"""AnthropicScreener: a malformed reply is a quarantine verdict, never ``clean`` (ADR-076-feedback-ticketing).

Every body here is a recorded fixture from evals/feedback-screening-v1/recorded,
replayed through ``httpx.MockTransport``. No test reaches the network and no
fixture holds a key.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from syn_adapters.feedback_screening import (
    AnthropicModelId,
    AnthropicScreener,
    ScreeningUnavailableError,
    parse_screening_reply,
)
from syn_domain.contexts.feedback import ScreenedText, ScreeningVerdict, TicketType

pytestmark = pytest.mark.unit

_RECORDED = (
    Path(__file__).resolve().parents[5]
    / "evals"
    / "feedback-screening-v1"
    / "recorded"
    / "claude-haiku-5-5.jsonl"
)
_FAKE_KEY = "test-key-not-a-secret"


def _recorded() -> dict[str, tuple[str, str | None]]:
    rows = [json.loads(line) for line in _RECORDED.read_text().splitlines() if line.strip()]
    return {row["case_id"]: (row["body"], row.get("note")) for row in rows}


def _malformed_case_ids() -> list[str]:
    return sorted(
        cid for cid, (_, note) in _recorded().items() if note and note.startswith("malformed")
    )


def test_the_recordings_include_every_malformed_shape() -> None:
    # Guards the parametrised test below against silently testing nothing.
    assert _malformed_case_ids() == [
        "inj-forget-2",
        "inj-roleplay-3",
        "spam-loan-2",
        "spam-pharma-1",
    ]


@pytest.mark.parametrize("case_id", _malformed_case_ids())
def test_a_malformed_recorded_reply_is_quarantine(case_id: str) -> None:
    body, _ = _recorded()[case_id]

    result = parse_screening_reply(body.encode())

    assert result.verdict is ScreeningVerdict.QUARANTINE


def test_a_clean_verdict_carrying_an_extra_key_is_still_quarantine() -> None:
    # The model said "clean" and added a field: the closed schema must win.
    body, _ = _recorded()["inj-forget-2"]
    assert '"verdict": "clean"' in body

    assert parse_screening_reply(body.encode()).verdict is ScreeningVerdict.QUARANTINE


@pytest.mark.parametrize("body", [b"", b"not json", b"{}", b'{"content": "text"}', b"[]"])
def test_a_body_that_is_not_a_messages_response_is_quarantine(body: bytes) -> None:
    assert parse_screening_reply(body).verdict is ScreeningVerdict.QUARANTINE


def test_two_tool_calls_are_quarantine_not_the_first_one() -> None:
    block = {
        "type": "tool_use",
        "name": "record_screening",
        "input": {"verdict": "clean", "type": "bug", "priority": "P2", "confidence": 0.9},
    }
    body = json.dumps({"content": [block, block]}).encode()

    assert parse_screening_reply(body).verdict is ScreeningVerdict.QUARANTINE


async def test_screen_sends_the_explicit_model_and_a_closed_forced_tool() -> None:
    sent: list[httpx.Request] = []
    body, _ = _recorded()["spam-casino-1"]

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(200, content=body.encode())

    async with httpx.AsyncClient(
        base_url="https://anthropic.test", transport=httpx.MockTransport(handler)
    ) as client:
        screener = AnthropicScreener(client, api_key=_FAKE_KEY, model=AnthropicModelId.SONNET_5_5)
        result = await screener.screen(ScreenedText.screen("Casino jackpot giveaway!"))

    assert result.verdict is ScreeningVerdict.SPAM
    assert result.type is TicketType.OTHER
    (request,) = sent
    assert request.url.path == "/v1/messages"
    assert request.headers["x-api-key"] == _FAKE_KEY
    payload = json.loads(request.content)
    assert payload["model"] == "claude-sonnet-5-5"
    assert payload["tool_choice"] == {"type": "tool", "name": "record_screening"}
    schema = payload["tools"][0]["input_schema"]
    assert schema["additionalProperties"] is False
    assert sorted(schema["required"]) == ["confidence", "priority", "type", "verdict"]
    assert "<feedback>Casino jackpot giveaway!</feedback>" in payload["messages"][0]["content"]


@pytest.mark.parametrize("status", [429, 500, 529])
async def test_no_reply_raises_so_the_screener_can_retry(status: int) -> None:
    transport = httpx.MockTransport(lambda _: httpx.Response(status, content=b"overloaded"))
    async with httpx.AsyncClient(base_url="https://anthropic.test", transport=transport) as client:
        screener = AnthropicScreener(client, api_key=_FAKE_KEY, model=AnthropicModelId.HAIKU_5_5)
        with pytest.raises(ScreeningUnavailableError, match=str(status)):
            await screener.screen(ScreenedText.screen("the export button crashes"))


async def test_a_transport_failure_raises_with_its_cause() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    async with httpx.AsyncClient(
        base_url="https://anthropic.test", transport=httpx.MockTransport(handler)
    ) as client:
        screener = AnthropicScreener(client, api_key=_FAKE_KEY, model=AnthropicModelId.HAIKU_5_5)
        with pytest.raises(ScreeningUnavailableError) as raised:
            await screener.screen(ScreenedText.screen("the export button crashes"))

    assert isinstance(raised.value.__cause__, httpx.ConnectError)


def test_model_ids_are_explicit_never_aliases() -> None:
    for model in AnthropicModelId:
        assert model.value.startswith("claude-")
        assert "latest" not in model.value
        assert model.value.count("-") >= 3, model.value
