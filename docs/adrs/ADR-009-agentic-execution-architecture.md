# ADR-009: Agentic Execution Architecture

**Status:** Accepted (Execution Model Superseded by ADR-023)
**Date:** 2025-12-02
**Deciders:** @neural
**Tags:** agents, agentic-sdk, claude-agent-sdk, paradigm-shift

> **Note:** This ADR defines the agentic protocol and workspace concept. The **execution model**
> (how `WorkflowExecutionEngine` uses workspaces and persists events) is specified in
> **[ADR-023: Workspace-First Execution Model](./ADR-023-workspace-first-execution-model.md)**.
>
> Key additions in ADR-023:
> - `WorkspaceRouter` is a **required** dependency for execution
> - `LocalWorkspace` **fails** in non-test environments
> - Events are **persisted** via aggregate pattern (not just logged)

## Context

The Agentic Engineering Framework (AEF) was initially implemented with a **chat completion model** where agents are thin wrappers around LLM APIs (Anthropic Messages API, OpenAI Chat API). This model is fundamentally misaligned with the framework's purpose.

### Current (Incorrect) Architecture

```python
# Current: Direct API calls - NOT agentic
class ClaudeAgent:
    async def complete(self, messages, config) -> AgentResponse:
        # Single request → Single response
        response = await client.messages.create(
            model=config.model,
            messages=converted_messages,
        )
        return AgentResponse(content=response.content[0].text)
```

**Problems with this approach:**

1. **Not Agentic**: Single request/response, no tool use, no multi-turn
2. **No Tool Support**: Agents can't Read, Write, Bash, Edit files
3. **Manual Hook Integration**: Hooks added via wrapper, not native
4. **Application Controls Flow**: Orchestrator decides when agent is "done"
5. **Name Mismatch**: "Agentic Engineering Framework" uses non-agentic patterns

### Desired Architecture

True agents that:
- Execute tasks autonomously until completion
- Use tools (Read, Write, Bash, Edit, etc.)
- Have built-in hook support via configuration
- Control their own execution flow
- Stream events as they work

## Decision

We will adopt an **Agentic SDK-first architecture** where agents are backed by agentic SDKs (like `claude-agent-sdk`) rather than raw LLM APIs.

### Core Principle: Agentic SDKs, Not APIs

| Abstraction Level | Example | Use In AEF |
|------------------|---------|------------|
| Raw LLM API | `anthropic.messages.create()` | ❌ **No** - Not agentic |
| Agentic SDK | `claude_agent_sdk.query()` | ✅ **Yes** - Full agent capabilities |
| CLI Wrapper | `subprocess.run(["claude", ...])` | ⚠️ Fallback only |

**Agentic SDKs provide:**
- Programmatic tool configuration (`allowed_tools=[...]`)
- System prompt injection
- Hook configuration (`setting_sources=["project"]`)
- Context/workspace management (`cwd=...`)
- Streaming event iteration
- Multi-turn execution until task completion

### New Agent Protocol

```python
class AgenticProtocol(Protocol):
    """Protocol for agentic task execution (not chat completion)."""

    @property
    def provider(self) -> AgentProvider:
        """Agent provider (claude, cursor, codex, etc.)."""
        ...

    @property
    def supported_tools(self) -> set[str]:
        """Tools this agent can use (Read, Write, Bash, etc.)."""
        ...

    async def execute(
        self,
        task: str,
        workspace: Workspace,
        config: AgentExecutionConfig,
    ) -> AsyncIterator[AgentEvent]:
        """Execute task in workspace, yielding events until done.

        The agent decides:
        - How many turns to take
        - Which tools to use
        - When the task is complete

        The orchestrator provides:
        - Task description
        - Workspace with context
        - Configuration (tools, hooks, budget)

        Yields:
            AgentEvent stream (tool calls, thinking, completion)
        """
        ...
```

### Claude Agent Implementation

```python
@dataclass
class ClaudeAgent:
    """Claude agent via claude-agent-sdk."""

    provider = AgentProvider.CLAUDE
    supported_tools = {"Read", "Write", "Edit", "MultiEdit", "Bash", "Glob", "Grep", "LS"}

    model: str = "claude-sonnet"

    async def execute(
        self,
        task: str,
        workspace: Workspace,
        config: AgentExecutionConfig,
    ) -> AsyncIterator[AgentEvent]:
        from claude_agent_sdk import ClaudeAgentOptions, query

        options = ClaudeAgentOptions(
            model=resolve_model(self.model),
            cwd=str(workspace.path),
            allowed_tools=list(self.supported_tools & config.allowed_tools),
            permission_mode=config.permission_mode,
            setting_sources=["project"],  # Reads .claude/settings.json for hooks
            max_turns=config.max_turns,
            max_budget_usd=config.max_budget_usd,
        )

        async for message in query(prompt=task, options=options):
            yield self._translate_to_agent_event(message)
```

### Workspace Architecture

Workspaces provide isolated execution environments with hooks pre-configured:

```
workspace-{session-id}/
├── .claude/
│   ├── settings.json          # Hook configuration
│   └── hooks/                  # From agentic-primitives
│       ├── handlers/
│       │   ├── pre-tool-use.py
│       │   ├── post-tool-use.py
│       │   └── user-prompt.py
│       └── validators/
│           ├── security/
│           │   ├── bash.py
│           │   └── file.py
│           └── prompt/
│               └── pii.py
├── .agentic/
│   └── analytics/
│       └── events.jsonl       # Hook events output
├── .context/                   # Injected from previous phases
│   ├── context.json
│   └── artifacts/
└── output/                     # Agent outputs captured here
```

### Workspace Adapters

```
WorkspaceProtocol
├── LocalWorkspace       (MVP - temp directories)
├── DockerWorkspace      (Isolation - pre-baked images)
└── CloudWorkspace       (Future - E2B, Modal, etc.)
```

### Artifact Bundle Model

Artifacts are collections of files with structured metadata:

```python
@dataclass
class ArtifactBundle:
    """A collection of files + structured metadata."""

    artifact_id: str
    phase_id: str
    bundle_type: str

    # Manifest of files
    files: list[ArtifactFile]

    # Structured output for next phase
    structured_output: dict[str, Any]

    # What to include in next phase context
    context_config: ContextConfig
```

### Event Bridge: Hooks → Domain Events

Hook events from `.agentic/analytics/events.jsonl` are bridged to AEF domain events:

```
Agent Execution
      │
      ▼
.claude/hooks/ (fire automatically)
      │
      ▼
.agentic/analytics/events.jsonl
      │
      ▼
EventBridge (watches JSONL)
      │
      ▼
AEF Event Store (domain events)
```

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         AEF Workflow Orchestrator                            │
│  - Manages workflow phases                                                   │
│  - Provides tasks + context to agents                                        │
│  - Collects artifacts for next phase                                         │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           AgenticProtocol                                    │
│  execute(task, workspace, config) -> AsyncIterator[AgentEvent]              │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
           ┌────────────────────────┼────────────────────────┐
           ▼                        ▼                        ▼
┌──────────────────┐    ┌──────────────────┐    ┌──────────────────┐
│   ClaudeAgent    │    │   CursorAgent    │    │   CodexAgent     │
│                  │    │   (future)       │    │   (future)       │
│ claude-agent-sdk │    │ cursor-sdk       │    │ openai-codex-sdk │
│                  │    │ (when available) │    │ (when available) │
└────────┬─────────┘    └──────────────────┘    └──────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                              Workspace                                       │
│  ┌─────────────────────────────────────────────────────────────────────────┐ │
│  │  .claude/hooks/ (from agentic-primitives)                                │ │
│  │    - Validators run automatically via settings.json                      │ │
│  │    - Events logged to .agentic/analytics/events.jsonl                   │ │
│  └─────────────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         Event Bridge → Event Store                           │
│  Hook events (JSONL) → Translated → AEF Domain Events                       │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Consequences

### Positive

✅ **True Agentic Behavior**: Multi-turn, tool use, autonomous completion

✅ **Framework Name Match**: "Agentic Engineering Framework" actually uses agents

✅ **Built-in Hooks**: Security and analytics via agentic-primitives

✅ **Provider Extensible**: New agentic SDKs plug in via protocol

✅ **Workspace Isolation**: Each execution gets isolated environment

✅ **Context Flow**: Artifacts naturally flow between phases

### Negative

⚠️ **SDK Dependency**: Tied to claude-agent-sdk for Claude (but SDK-first is intentional)

⚠️ **Workspace Overhead**: Setting up hooks per workspace

⚠️ **Event Bridge Complexity**: Need to translate between hook events and domain events

### Mitigations

1. **SDK Abstraction**: Protocol allows swapping SDKs without code changes
2. **Workspace Templates**: Pre-configure hooks, copy on workspace creation
3. **Event Bridge Patterns**: Well-defined translation layer with canonical event types

## Implementation

See: `PROJECT-PLAN_20251202_AGENTIC-SDK-INTEGRATION.md`

## Related ADRs

- **ADR-006**: Hook Architecture for Agent Swarms (hooks infrastructure)
- **ADR-007**: Event Store Integration (domain events)
- **ADR-001**: Monorepo Architecture (package structure)

## References

- [claude-agent-sdk documentation](https://github.com/anthropics/claude-agent-sdk)
- [agentic-primitives hooks](../../lib/agentic-primitives/docs/hooks/README.md)
- [Example: 001-claude-agent-sdk-integration](../../lib/agentic-primitives/examples/001-claude-agent-sdk-integration/)
