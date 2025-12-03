"""Tests for InstrumentedAgent wrapper.

Tests cover:
- Session context management
- Hook event emission for requests
- Tool validation integration
- Streaming with instrumentation
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from agentic_hooks import EventType

from aef_adapters.agents import (
    AgentConfig,
    AgentMessage,
    AgentProvider,
    InstrumentedAgent,
    MockAgent,
    MockAgentConfig,
    SessionContext,
)
from aef_adapters.hooks import AEFHookClient, ValidatorRegistry


class TestSessionContext:
    """Tests for SessionContext."""

    def test_minimal_context(self) -> None:
        """Test context with only session_id."""
        ctx = SessionContext(session_id="test-123")
        assert ctx.session_id == "test-123"
        assert ctx.workflow_id is None
        assert ctx.phase_id is None

    def test_full_context(self) -> None:
        """Test context with all fields."""
        ctx = SessionContext(
            session_id="session-123",
            workflow_id="workflow-456",
            phase_id="research",
            milestone_id="m1",
            metadata={"key": "value"},
        )
        assert ctx.session_id == "session-123"
        assert ctx.workflow_id == "workflow-456"
        assert ctx.phase_id == "research"
        assert ctx.milestone_id == "m1"
        assert ctx.metadata == {"key": "value"}

    def test_to_dict_minimal(self) -> None:
        """Test to_dict with minimal context."""
        ctx = SessionContext(session_id="test-123")
        data = ctx.to_dict()
        assert data == {"session_id": "test-123"}

    def test_to_dict_full(self) -> None:
        """Test to_dict with full context."""
        ctx = SessionContext(
            session_id="s1",
            workflow_id="w1",
            phase_id="p1",
            milestone_id="m1",
            metadata={"extra": "data"},
        )
        data = ctx.to_dict()
        assert data == {
            "session_id": "s1",
            "workflow_id": "w1",
            "phase_id": "p1",
            "milestone_id": "m1",
            "metadata": {"extra": "data"},
        }

    def test_with_metadata(self) -> None:
        """Test with_metadata creates new context."""
        ctx = SessionContext(
            session_id="s1",
            workflow_id="w1",
            metadata={"existing": "value"},
        )
        new_ctx = ctx.with_metadata(new_key="new_value")

        # Original unchanged
        assert ctx.metadata == {"existing": "value"}

        # New context has merged metadata
        assert new_ctx.session_id == "s1"
        assert new_ctx.workflow_id == "w1"
        assert new_ctx.metadata == {"existing": "value", "new_key": "new_value"}

    def test_immutable(self) -> None:
        """Test that SessionContext is immutable."""
        ctx = SessionContext(session_id="test")
        with pytest.raises(AttributeError):
            ctx.session_id = "changed"  # type: ignore[misc]


class TestInstrumentedAgent:
    """Tests for InstrumentedAgent."""

    @pytest.fixture
    def mock_agent(self) -> MockAgent:
        """Create mock agent."""
        return MockAgent(MockAgentConfig(responses=["Test response"]))

    @pytest.fixture
    def mock_hook_client(self) -> AEFHookClient:
        """Create mock hook client."""
        with patch("aef_shared.settings.get_settings") as mock_get:
            mock_get.return_value = MagicMock(
                hook_backend_url=None,
                hook_batch_size=50,
                hook_flush_interval_seconds=1.0,
            )
            client = AEFHookClient.from_settings()
            # Mock the emit method
            client._client.emit = AsyncMock()  # type: ignore[method-assign]
            return client

    @pytest.fixture
    def instrumented(
        self, mock_agent: MockAgent, mock_hook_client: AEFHookClient
    ) -> InstrumentedAgent:
        """Create instrumented agent."""
        return InstrumentedAgent(
            agent=mock_agent,
            hook_client=mock_hook_client,
            validators=ValidatorRegistry(),
        )

    def test_provider_passthrough(self, instrumented: InstrumentedAgent) -> None:
        """Test provider property passes through."""
        assert instrumented.provider == AgentProvider.MOCK

    def test_is_available_passthrough(self, instrumented: InstrumentedAgent) -> None:
        """Test is_available property passes through."""
        assert instrumented.is_available is True

    def test_set_session_context(self, instrumented: InstrumentedAgent) -> None:
        """Test setting session context."""
        instrumented.set_session_context(
            session_id="sess-123",
            workflow_id="wf-456",
            phase_id="research",
        )
        assert instrumented._session_context is not None
        assert instrumented._session_context.session_id == "sess-123"
        assert instrumented._session_context.workflow_id == "wf-456"
        assert instrumented._session_context.phase_id == "research"

    def test_clear_session_context(self, instrumented: InstrumentedAgent) -> None:
        """Test clearing session context."""
        instrumented.set_session_context("test")
        assert instrumented._session_context is not None
        instrumented.clear_session_context()
        assert instrumented._session_context is None

    @pytest.mark.asyncio
    async def test_complete_emits_events(
        self, instrumented: InstrumentedAgent, mock_hook_client: AEFHookClient
    ) -> None:
        """Test that complete() emits start and completed events."""
        instrumented.set_session_context("sess-123", workflow_id="wf-456")

        messages = [AgentMessage.user("Hello!")]
        config = AgentConfig(model="test-model", max_tokens=100)

        response = await instrumented.complete(messages, config)

        # Verify response
        assert response.content == "Test response"

        # Verify events were emitted
        emit_mock = mock_hook_client._client.emit
        assert emit_mock.call_count == 2

        # Check start event
        start_event = emit_mock.call_args_list[0][0][0]
        assert start_event.event_type == EventType.AGENT_REQUEST_STARTED
        assert start_event.session_id == "sess-123"
        assert start_event.workflow_id == "wf-456"
        assert start_event.data["message_count"] == 1
        assert start_event.data["model"] == "test-model"

        # Check completed event
        completed_event = emit_mock.call_args_list[1][0][0]
        assert completed_event.event_type == EventType.AGENT_REQUEST_COMPLETED
        assert completed_event.session_id == "sess-123"
        assert "total_tokens" in completed_event.data
        assert "duration_seconds" in completed_event.data

    @pytest.mark.asyncio
    async def test_complete_without_context(
        self, instrumented: InstrumentedAgent, mock_hook_client: AEFHookClient
    ) -> None:
        """Test complete() works without session context."""
        messages = [AgentMessage.user("Test")]
        config = AgentConfig(model="test")

        response = await instrumented.complete(messages, config)
        assert response is not None

        # Events should use "unknown" for session_id
        emit_mock = mock_hook_client._client.emit
        start_event = emit_mock.call_args_list[0][0][0]
        assert start_event.session_id == "unknown"

    @pytest.mark.asyncio
    async def test_validate_tool_use_allowed(
        self, instrumented: InstrumentedAgent, mock_hook_client: AEFHookClient
    ) -> None:
        """Test tool validation for allowed command."""
        instrumented.set_session_context("sess-123")

        result = await instrumented.validate_tool_use("Bash", {"command": "ls -la"})

        assert result.safe is True

        # Should emit tool execution started
        emit_mock = mock_hook_client._client.emit
        assert emit_mock.call_count == 1
        event = emit_mock.call_args_list[0][0][0]
        assert event.event_type == EventType.TOOL_EXECUTION_STARTED
        assert event.data["tool_name"] == "Bash"

    @pytest.mark.asyncio
    async def test_validate_tool_use_blocked(
        self, instrumented: InstrumentedAgent, mock_hook_client: AEFHookClient
    ) -> None:
        """Test tool validation blocks dangerous command."""
        instrumented.set_session_context("sess-123")

        result = await instrumented.validate_tool_use("Bash", {"command": "rm -rf /"})

        assert result.safe is False

        # Should emit tool started and tool blocked
        emit_mock = mock_hook_client._client.emit
        assert emit_mock.call_count == 2

        blocked_event = emit_mock.call_args_list[1][0][0]
        assert blocked_event.event_type == EventType.TOOL_BLOCKED
        assert blocked_event.data["tool_name"] == "Bash"
        assert blocked_event.data["reason"] is not None

    @pytest.mark.asyncio
    async def test_validate_tool_use_no_validators(
        self, mock_agent: MockAgent, mock_hook_client: AEFHookClient
    ) -> None:
        """Test validation without validators allows everything."""
        instrumented = InstrumentedAgent(
            agent=mock_agent,
            hook_client=mock_hook_client,
            validators=None,  # No validators
        )
        instrumented.set_session_context("sess-123")

        result = await instrumented.validate_tool_use("Bash", {"command": "rm -rf /"})

        # Should allow since no validators
        assert result.safe is True

    @pytest.mark.asyncio
    async def test_emit_tool_completed(
        self, instrumented: InstrumentedAgent, mock_hook_client: AEFHookClient
    ) -> None:
        """Test emitting tool completed event."""
        instrumented.set_session_context("sess-123")

        await instrumented.emit_tool_completed(
            tool_name="Write",
            success=True,
            duration_seconds=0.5,
            metadata={"file_path": "test.py"},
        )

        emit_mock = mock_hook_client._client.emit
        assert emit_mock.call_count == 1

        event = emit_mock.call_args_list[0][0][0]
        assert event.event_type == EventType.TOOL_EXECUTION_COMPLETED
        assert event.data["tool_name"] == "Write"
        assert event.data["success"] is True
        assert event.data["duration_seconds"] == 0.5
        assert event.data["file_path"] == "test.py"

    @pytest.mark.asyncio
    async def test_stream_emits_events(
        self, instrumented: InstrumentedAgent, mock_hook_client: AEFHookClient
    ) -> None:
        """Test that stream() emits start and completed events."""
        instrumented.set_session_context("sess-123")

        messages = [AgentMessage.user("Hello!")]
        config = AgentConfig(model="test-model")

        chunks = []
        async for chunk in instrumented.stream(messages, config):
            chunks.append(chunk)

        # Verify chunks received
        assert len(chunks) == 3  # Default mock chunks
        assert "".join(chunks) == "Mock streaming response"

        # Verify events
        emit_mock = mock_hook_client._client.emit
        assert emit_mock.call_count == 2

        # Check start event
        start_event = emit_mock.call_args_list[0][0][0]
        assert start_event.event_type == EventType.AGENT_REQUEST_STARTED
        assert start_event.data["streaming"] is True

        # Check completed event
        completed_event = emit_mock.call_args_list[1][0][0]
        assert completed_event.event_type == EventType.AGENT_REQUEST_COMPLETED
        assert completed_event.data["streaming"] is True
        assert completed_event.data["chunk_count"] == 3


class TestInstrumentedAgentIntegration:
    """Integration tests using real hook client (JSONL backend)."""

    @pytest.mark.asyncio
    async def test_full_workflow_simulation(self) -> None:
        """Test simulating a full workflow with instrumented agent."""
        with patch("aef_shared.settings.get_settings") as mock_get:
            mock_get.return_value = MagicMock(
                hook_backend_url=None,
                hook_batch_size=50,
                hook_flush_interval_seconds=1.0,
            )

            mock_agent = MockAgent(
                MockAgentConfig(responses=["Research findings", "Implementation plan"])
            )

            async with AEFHookClient.from_settings() as client:
                instrumented = InstrumentedAgent(
                    agent=mock_agent,
                    hook_client=client,
                    validators=ValidatorRegistry(),
                )

                # Phase 1: Research
                instrumented.set_session_context(
                    session_id="sess-001",
                    workflow_id="wf-demo",
                    phase_id="research",
                )

                response1 = await instrumented.complete(
                    [AgentMessage.user("Research AI agents")],
                    AgentConfig(model="mock"),
                )
                assert response1.content == "Research findings"

                # Phase 2: Planning
                instrumented.set_session_context(
                    session_id="sess-002",
                    workflow_id="wf-demo",
                    phase_id="planning",
                )

                response2 = await instrumented.complete(
                    [AgentMessage.user("Create plan based on: " + response1.content)],
                    AgentConfig(model="mock"),
                )
                assert response2.content == "Implementation plan"

                # Verify agent was called correctly
                assert mock_agent.call_count == 2
