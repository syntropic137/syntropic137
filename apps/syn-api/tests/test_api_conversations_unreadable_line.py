"""An unreadable stored line fails the conversation log request (#1424).

The reader returns an ``UnreadableConversationLine`` instead of raising; the
route must still answer QUERY_FAILED with the cause's message, which is what a
raising parser produced before the parsing moved behind the port.
"""

import os
from unittest.mock import AsyncMock, patch

import pytest

from syn_api.types import Err, ObservabilityError

pytestmark = pytest.mark.unit

os.environ.setdefault("APP_ENVIRONMENT", "test")


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ('{"type": []}', "unhashable type: 'list'"),
        ('{"message": {"content": [{"text": 3}]}}', "'int' object is not subscriptable"),
        ('{"type": 3}', "event_type must be a string, got int: 3"),
    ],
)
async def test_unreadable_line_fails_the_log_with_its_cause(raw: str, message: str) -> None:
    from syn_api.routes.conversations import get_conversation_log

    store = AsyncMock()
    store.retrieve_session = AsyncMock(return_value=['{"type": "user"}', raw])
    with (
        patch("syn_api.routes.conversations.ensure_connected", new=AsyncMock()),
        patch(
            "syn_api.routes.conversations.get_conversation_store",
            new=AsyncMock(return_value=store),
        ),
    ):
        result = await get_conversation_log("unreadable-1")

    assert isinstance(result, Err)
    assert result.error == ObservabilityError.QUERY_FAILED
    assert result.message == message
