# 🧠 Observability Investigation Session
**Date:** 2025-12-16
**Focus:** Full E2E Observability (Tokens ✅, Tools ✅)

---

## 🎯 Current State (Updated 2025-12-16 18:45)

### ✅ What's Working (MAJOR WINS!)
- **TimescaleDB Integration**: Fully operational, 10x-100x faster than event store for observations
- **ObservabilityWriter**: Proven at 2000+ observations/sec in isolated tests
- **Token Usage Capture**: End-to-end working (container → TimescaleDB → API → UI)
- **Tool Started Capture**: 19 tool_started events captured via SDK message parsing!
- **Cost Calculation**: Accurate, validated against manual calculations
- **Fast Unit Tests**: 15 tests in 0.24s - validates parsing without Claude API

**Evidence:**
```sql
SELECT observation_type, COUNT(*) FROM agent_observations
GROUP BY observation_type;

 observation_type | count
------------------+-------
 tool_started     |    19   ← NEW: Bash, Write, Read, TodoWrite!
 token_usage      |     5
```

**Tool Details:**
```sql
SELECT data->>'tool_name' as tool, COUNT(*) FROM agent_observations
WHERE observation_type = 'tool_started' GROUP BY data->>'tool_name';

 tool      | count
-----------+-------
 Bash      |     2
 Write     |     5
 TodoWrite |     8
 Read      |     4
```

### 🔄 What Needs Wiring (Not Bugs - Integration Work)
- **Dashboard API Tool Endpoint**: Currently queries event store projections, needs to query TimescaleDB
- **Tool Completed Events**: SDK doesn't yield ToolResultBlock to callers (handled internally)
- **Operations Timeline UI**: Needs to consume tool data from TimescaleDB

### Key Architecture Discovery
The Claude SDK's `query()` function yields:
1. `AssistantMessage` with `ToolUseBlock` → we capture `tool_started` ✅
2. SDK executes tool **internally** (doesn't yield result)
3. Claude continues → next `AssistantMessage`

**Implication**: `tool_completed` events need to be inferred from sequence, not explicit messages.

---

## 🔍 Root Cause Discovery

### The Hook Problem
**What we configured:**
```python
# packages/aef-agent-runner/src/aef_agent_runner/hooks.py
hooks["PreToolUse"] = [HookMatcher(hooks=[on_pre_tool_use])]   # Should capture tool started
hooks["PostToolUse"] = [HookMatcher(hooks=[on_post_tool_use])] # Should capture tool completed
```

**What we expected:**
- `on_pre_tool_use()` → emits `tool_use` event → captured in WorkflowExecutionEngine
- `on_post_tool_use()` → emits `tool_result` event → captured in WorkflowExecutionEngine

**What actually happened:**
```bash
# From LOG_LEVEL=DEBUG workflow run:
grep -c "PreToolUse\|PostToolUse" /tmp/workflow-debug-full.log
# Result: 0 ← HOOKS NEVER FIRED!
```

### Why Hooks Don't Fire

**Hypothesis:** Claude Code SDK's **built-in tools bypass Python hooks**

The Claude SDK has native C++/TypeScript tools (bash, Write, Read, gh, etc.) that are:
1. Implemented in the SDK runtime (not Python)
2. Executed before hook matchers run
3. Never passed through the Python hook system

**Supporting evidence:**
- Token usage hooks work (they fire on API responses)
- Tool hooks don't fire (tools execute in SDK runtime)
- Agent successfully used tools (PR was created, files were written)
- Zero hook logs despite `enable_observability=True`

---

## 🛠️ Potential Solutions

### Option 1: SDK Stream Events (RECOMMENDED)
**Approach:** Parse tool events from Claude SDK's streaming response

**What we know:**
```python
# From packages/aef-agent-runner/src/aef_agent_runner/runner.py
async for stream_event in agent.run_task(task, stream=True):
    event_data = stream_event.to_dict()
    event_type = event_data.get("type", "")

    # Current: Only parsing "usage" for tokens
    # Missing: Parsing tool_use blocks from messages
```

**Research needed:**
1. What event types does `stream_event` emit?
2. Does it include `content_block_start` with `tool_use` type?
3. Can we extract tool_name, tool_input, tool_use_id from stream?
4. What about tool results - are they in `tool_result` content blocks?

**File to investigate:**
```
@docs/deps/python/claude-agent-sdk@latest-20251216.md
```
Search for: "StreamEvent", "content_block", "tool_use", "tool_result"

---

### Option 2: Stdout Parsing (HACKY)
**Approach:** Parse agent stdout for tool execution traces

**Pros:**
- Might work if SDK prints tool calls
- No SDK changes needed

**Cons:**
- Fragile (depends on SDK log format)
- Not guaranteed to have all data (tool_use_id, duration, etc.)
- Not a proper observability solution

---

### Option 3: Custom Tool Definitions (COMPLEX)
**Approach:** Replace SDK built-in tools with Python wrappers that emit events

**Pros:**
- Full control over observability
- Hooks would fire on our tools

**Cons:**
- Massive refactor (reimplementing bash, Write, Read, etc.)
- Lose SDK features (permission handling, safety checks)
- High maintenance burden
- Defeats purpose of using Claude Code SDK

---

## 📋 Next Steps (Priority Order)

### 🔥 IMMEDIATE (Tomorrow Morning)

1. **Research SDK Stream Events** (30-60 min)
   ```bash
   # Open the SDK docs we have
   code @docs/deps/python/claude-agent-sdk@latest-20251216.md

   # Search for these patterns:
   - "StreamEvent" type definitions
   - "content_block_start" / "content_block_delta"
   - "tool_use" in message content
   - "tool_result" in message content
   ```

   **Goal:** Determine if SDK streams contain tool execution data

2. **Prototype Stream Parser** (1-2 hours)
   - If SDK streams have tool data, add parsing to `runner.py`
   - Test in isolation with a simple agent task
   - Verify we can extract: tool_name, tool_use_id, input, output

3. **Integrate Stream Parsing** (2-3 hours)
   - Update `aef-agent-runner` to emit `tool_use` and `tool_result` events
   - Update `WorkflowExecutionEngine` event parsing (already has code, just not receiving events)
   - Test full E2E: agent → stream → JSONL → TimescaleDB → Dashboard

---

### 🎯 VALIDATION TEST

Once implemented, run:
```bash
# Run workflow with tool-heavy task
uv run aef workflow run github-pr --container

# Check TimescaleDB for tool events
docker exec aef-timescaledb psql -U aef -d aef_observability -c "
SELECT observation_type, COUNT(*)
FROM agent_observations
GROUP BY observation_type
ORDER BY COUNT(*) DESC;
"

# Expected:
# observation_type | count
# ------------------+-------
# tool_completed   |    15
# tool_started     |    15
# token_usage      |     3
```

**Success criteria:**
- `tool_started` and `tool_completed` events in TimescaleDB ✅
- Dashboard UI shows operations timeline ✅
- Tool call details visible (tool name, duration) ✅

---

## 📚 Key Files Reference

### Where the problem is:
```
packages/aef-agent-runner/src/aef_agent_runner/runner.py:316
  ↳ Only parsing "usage" from stream_event.to_dict()
  ↳ Need to parse tool_use content blocks
```

### Where the fix goes:
```
packages/aef-agent-runner/src/aef_agent_runner/runner.py:316-336
  ↳ Add content_block parsing
  ↳ Emit tool_use/tool_result events

packages/aef-agent-runner/src/aef_agent_runner/events.py:140-166
  ↳ emit_tool_use() and emit_tool_result() already exist
  ↳ Just need to call them with correct data
```

### Already working (don't touch):
```
packages/aef-domain/.../WorkflowExecutionEngine.py:982-1043
  ↳ Correctly parses tool_use/tool_result from JSONL
  ↳ Writes to TimescaleDB via ObservabilityWriter

packages/aef-adapters/.../observability_writer.py
  ↳ Proven working, handles 2000+ obs/sec

apps/aef-dashboard/src/aef_dashboard/api/sessions.py
  ↳ Queries TimescaleDB, ready for tool data
```

---

## 💭 Mental Model

**Current Flow (Tokens):**
```
Agent execution
  → SDK emits usage in stream
  → runner.py parses usage
  → emit_token_usage()
  → stdout JSONL
  → WorkflowExecutionEngine parses
  → ObservabilityWriter.record_observation()
  → TimescaleDB
  → SessionCostProjection queries
  → Dashboard API
  → UI ✅
```

**Missing Flow (Tools):**
```
Agent execution
  → SDK executes tool (bash, Write, etc.)
  → ??? SDK stream has tool data? ???
  → runner.py SHOULD parse tool content blocks ← FIX HERE
  → emit_tool_use() / emit_tool_result()
  → stdout JSONL
  → WorkflowExecutionEngine parses (ALREADY READY)
  → ObservabilityWriter.record_observation() (ALREADY READY)
  → TimescaleDB (ALREADY READY)
  → SessionCostProjection queries (ALREADY READY)
  → Dashboard API (ALREADY READY)
  → UI ❌ (waiting for data)
```

**The gap:** Step 2-3 in the "Missing Flow" - we're not parsing tool events from SDK stream.

---

## 🚨 Risks & Considerations

1. **SDK Stream Limitations**
   - If SDK doesn't emit tool events in stream, we're blocked
   - May need to file issue with Anthropic
   - Fallback: Parse SDK logs (hacky but might work)

2. **Performance Impact**
   - Parsing every stream event adds latency
   - Need to ensure non-blocking parsing
   - TimescaleDB can handle volume (proven)

3. **Data Completeness**
   - SDK stream might not have all data we want
   - May need to synthesize tool_use_id if not provided
   - Duration calculation might require timing on our side

---

## 🎉 Wins Today

Despite the tool hook issue, we achieved **massive architectural progress**:

1. **Separated observability from domain events** (ADR-026)
2. **Integrated TimescaleDB** with 10x-100x performance improvement
3. **Validated full token observability pipeline** end-to-end
4. **Dashboard displaying real-time cost data** from workflows
5. **Edge-first testing strategy** proving components in isolation

**The infrastructure is solid.** We just need to find the right event source for tool data.

---

## 📝 Tomorrow's Checklist

- [ ] Read SDK docs for StreamEvent types
- [ ] Find tool_use/tool_result in stream content
- [ ] Prototype stream parser in runner.py
- [ ] Test isolated agent with tool calls
- [ ] Verify JSONL output has tool events
- [ ] Run E2E test and check TimescaleDB
- [ ] Confirm Dashboard shows tool data
- [ ] Update PROJECT-PLAN with findings
- [ ] Document stream parsing approach in ADR

---

## 🔗 Related Documentation

- **ADR-026**: TimescaleDB Observability Storage
- **ADR-018**: Commands vs Observations Event Architecture
- **PROJECT-PLAN_20251216_EDGE-FIRST-OBSERVABILITY.md**: Implementation strategy (M1-M5 complete, M6 blocked)
- **E2E-OBSERVABILITY-TEST-PLAN.md**: Validation criteria (tokens ✅, tools ❌)

---

## 💡 Key Insight

**The problem isn't our architecture - it's the event source.**

Everything downstream works perfectly:
- JSONL parsing ✅
- TimescaleDB writes ✅
- Cost projection ✅
- Dashboard API ✅

We just need to **emit the tool events** from the runner, and the entire pipeline lights up. 🚀

---

**Tomorrow:** Focus on SDK stream events. That's the unlock. 🔓
