# observability

Metrics and telemetry — token usage and tool timelines.

**Status:** Stub — all functions return `Err(ObservabilityError.NOT_IMPLEMENTED)`.

## get_token_metrics()

Get token usage metrics for an execution or session.

**Signature:**

```python
async def get_token_metrics(
    execution_id: str | None = None,
    session_id: str | None = None,
    auth: AuthContext | None = None,
) -> Result[dict[str, Any], ObservabilityError]
```

---

## get_tool_timeline()

Get the tool call timeline for a session.

**Signature:**

```python
async def get_tool_timeline(
    session_id: str,
    auth: AuthContext | None = None,
) -> Result[list[dict[str, Any]], ObservabilityError]
```
