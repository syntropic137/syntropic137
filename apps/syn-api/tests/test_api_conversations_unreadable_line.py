"""An unreadable stored line fails the conversation log request (#1424).

The reader returns an ``UnreadableConversationLine`` instead of raising; the
route must still answer QUERY_FAILED with the cause's message, which is what a
raising parser produced before the parsing moved behind the port. A non-string
event type used to fail ``ConversationLine`` validation, so its message is that
validation error's, exactly as before.
"""

import os
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import ValidationError

from syn_api.types import ConversationLog, Err, ObservabilityError, Result

pytestmark = pytest.mark.unit

os.environ.setdefault("APP_ENVIRONMENT", "test")


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ('{"type": []}', "unhashable type: 'list'"),
        ('{"message": {"content": [{"text": 3}]}}', "'int' object is not subscriptable"),
    ],
)
async def test_unreadable_line_fails_the_log_with_its_cause(raw: str, message: str) -> None:
    result = await _log_of(raw)

    assert isinstance(result, Err)
    assert result.error == ObservabilityError.QUERY_FAILED
    assert result.message == message


@pytest.mark.parametrize(
    ("raw", "value", "input_type"),
    [
        ('{"type": 3}', 3, "int"),
        ('{"event_type": 7}', 7, "int"),
        ('{"type": 1.5}', 1.5, "float"),
        ('{"type": true}', True, "bool"),
        ('{"event_type": ["x"]}', ["x"], "list"),
    ],
)
async def test_non_string_event_type_fails_with_the_response_model_validation_error(
    raw: str, value: object, input_type: str
) -> None:
    """The message the pre-#1424 route gave: ``ConversationLine`` rejecting the value."""
    from syn_api.types import ConversationLine

    with pytest.raises(ValidationError) as rejected:
        ConversationLine.model_validate(
            {"line_number": 2, "raw": raw, "event_type": value, "tool_name": None}
        )

    result = await _log_of(raw)

    assert isinstance(result, Err)
    assert result.error == ObservabilityError.QUERY_FAILED
    assert result.message == str(rejected.value)
    assert result.message.startswith(
        "1 validation error for ConversationLine\nevent_type\n"
        f"  Input should be a valid string [type=string_type, input_value={value!r}, "
        f"input_type={input_type}]"
    )


async def _log_of(raw: str) -> Result[ConversationLog, ObservabilityError]:
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
        return await get_conversation_log("unreadable-1")
