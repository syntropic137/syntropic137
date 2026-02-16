# sessions

Agent session lifecycle management.

## list_sessions()

List agent sessions, optionally filtered.

**Signature:**

```python
async def list_sessions(
    workflow_id: str | None = None,
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
    auth: AuthContext | None = None,
) -> Result[list[SessionSummary], SessionError]
```

**Parameters:**

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `workflow_id` | `str \| None` | `None` | Filter by workflow ID |
| `status` | `str \| None` | `None` | Filter by session status |
| `limit` | `int` | `100` | Maximum results |
| `offset` | `int` | `0` | Pagination offset |
| `auth` | `AuthContext \| None` | `None` | Optional auth context |

**Returns:** `Ok(list[SessionSummary])` on success.

**Example:**

```python
result = await aef_api.v1.sessions.list_sessions(workflow_id="wf-123")
match result:
    case Ok(sessions):
        for s in sessions:
            print(f"Session {s.id}: {s.status}, {s.total_tokens} tokens")
```

---

## start_session()

Start a new agent session.

**Signature:**

```python
async def start_session(
    workflow_id: str,
    phase_id: str | None = None,
    execution_id: str | None = None,
    agent_type: str = "claude",
    auth: AuthContext | None = None,
) -> Result[str, SessionError]
```

**Parameters:**

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `workflow_id` | `str` | required | Workflow this session belongs to |
| `phase_id` | `str \| None` | `None` | Phase within the workflow |
| `execution_id` | `str \| None` | `None` | Execution ID |
| `agent_type` | `str` | `"claude"` | Agent provider (claude, openai, mock) |
| `auth` | `AuthContext \| None` | `None` | Optional auth context |

**Returns:** `Ok(session_id)` on success.

---

## complete_session()

Complete an agent session.

**Signature:**

```python
async def complete_session(
    session_id: str,
    auth: AuthContext | None = None,
) -> Result[None, SessionError]
```

**Returns:** `Ok(None)` on success, `Err(SessionError.NOT_FOUND)` if session doesn't exist.
