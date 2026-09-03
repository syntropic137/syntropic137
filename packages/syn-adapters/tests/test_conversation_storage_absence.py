"""``None`` from conversation storage is a claim, and only absence may make it.

The read path turns ``retrieve_session() is None`` into a statement to a user
about their session - at worst, that no agent ever ran for it. A store that
could not answer has no standing to make that statement, so it must not be
able to produce the same value as a store that answered "nothing here"
(#1065).
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from minio.error import S3Error

from syn_adapters.conversations.minio_session import retrieve_session

if TYPE_CHECKING:
    from syn_adapters.conversations.minio import MinioConversationStorage

pytestmark = pytest.mark.unit


def _s3_error(code: str) -> S3Error:
    return S3Error(
        response=MagicMock(),
        code=code,
        message=code,
        resource="sessions/sess-1/conversation.jsonl",
        request_id="req-1",
        host_id="host-1",
    )


def _storage(failure: Exception | None = None, body: bytes = b"") -> MinioConversationStorage:
    """A storage whose client either serves an object or fails a given way."""
    client = MagicMock()
    if failure is not None:
        client.get_object.side_effect = failure
    else:
        response = MagicMock()
        response.read.return_value = body
        client.get_object.return_value = response

    storage = MagicMock()
    storage._initialized = True
    storage._client = client
    storage.BUCKET_NAME = "conversations"
    return storage


@pytest.mark.anyio
async def test_a_stored_log_is_returned() -> None:
    lines = await retrieve_session(_storage(body=b'{"a": 1}\n{"b": 2}\n'), "sess-1")

    assert lines == ['{"a": 1}', '{"b": 2}']


@pytest.mark.anyio
@pytest.mark.parametrize("code", ["NoSuchKey", "NoSuchBucket"])
async def test_a_missing_object_is_absence(code: str) -> None:
    """The store answered, and the answer was that there is nothing there."""
    assert await retrieve_session(_storage(_s3_error(code)), "sess-1") is None


@pytest.mark.anyio
@pytest.mark.parametrize(
    "failure",
    [
        ConnectionError("minio unreachable"),
        TimeoutError("read timed out"),
        S3Error(
            response=MagicMock(),
            code="AccessDenied",
            message="AccessDenied",
            resource="r",
            request_id="q",
            host_id="h",
        ),
    ],
    ids=["outage", "timeout", "credentials"],
)
async def test_a_store_that_could_not_answer_raises(failure: Exception) -> None:
    """An outage must not be able to say "this session has no log".

    Every one of these used to return ``None``, which the read path reports as
    a missing - or never-started - session. They are indistinguishable from
    each other and from a genuine absence at that point, so the only place the
    difference survives is here, and the only way to keep it is to raise. The
    caller already maps a raised error to a failed query (#1065).
    """
    with pytest.raises(type(failure)):
        await retrieve_session(_storage(failure), "sess-1")
