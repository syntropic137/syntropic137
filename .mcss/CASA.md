# CURRENT ACTIVE STATE ARTIFACT (CASA)

**Project:** Agentic Engineering Framework
**Updated:** 2025-12-06
**Branch:** `main` (both repos synced)
**Status:** All synced ✅ | Primitives restructure complete ✅

---

## Where I Left Off

**Just completed the Primitives Directory Restructure** — a major refactoring to align `agentic-primitives` with Claude Code's `.claude/` directory standard. Both PRs merged:

- **agentic-primitives PR #22:** `f362fb9` (merged)
- **AEF PR #9:** `e0d242f` (merged)

New directory structure:
```
primitives/v1/
├── commands/{category}/{id}/      # /command-name
│   └── meta/{id}/                 # Meta-prompts
├── skills/{category}/{id}/        # Referenced in prompts
├── agents/{category}/{id}/        # @agent-name
├── tools/{category}/{id}/         # MCP integrations
└── hooks/{category}/{id}/         # Lifecycle handlers
```

## What To Do Next

### Priority 1: Context & Token Tracking

**Goal:** Accurately track and observe agent context usage.

| Metric | Description | Storage |
|--------|-------------|---------|
| `context_size` | Current context window usage | Per-session |
| `total_tokens_in` | Cumulative input tokens | Per-session |
| `total_tokens_out` | Cumulative output tokens | Per-session |
| `context_limit` | Model's max context | Per-agent config |

**Implementation:**
```python
# New event: ContextMetricsUpdated
@event("ContextMetricsUpdated", "v1")
class ContextMetricsUpdated:
    session_id: str
    context_size: int           # Current window
    total_tokens_in: int        # Cumulative
    total_tokens_out: int       # Cumulative
    context_limit: int          # Model max
    timestamp: datetime
```

**Key Insight:** `total_tokens_in/out` can exceed `context_size` due to context engineering (sliding window, summarization, etc.)

### Priority 2: Tool Usage Tracking

**Goal:** Full observability into tool invocations.

| Data Point | Description |
|------------|-------------|
| `tool_name` | Which tool was called |
| `tool_input` | Input parameters |
| `tool_output` | Return value/result |
| `duration_ms` | Execution time |
| `status` | success/error/timeout |
| `blocked_by_hook` | If safety hook prevented |

**Backend First:** Events capture all tool usage. UI is just a validation/display layer.

### Priority 3: Docker Workspace for Agentic Coding

**Goal:** Isolated, reproducible agent execution environment.

```yaml
# docker-compose.workspace.yaml
services:
  agent-workspace:
    build: ./workspace
    volumes:
      - ./repos:/workspace/repos   # Code to work on
      - ./artifacts:/workspace/out # Output artifacts
    environment:
      - ANTHROPIC_API_KEY
    security_opt:
      - no-new-privileges:true
```

**Safety:** Sandboxed file access, network restrictions, resource limits.

### Priority 4: Automated Engineering Workflows

**Goal:** Full-cycle automation from issue to merged PR.

```
Issue → Plan → Implement → Test → Review → Merge
  ↓       ↓        ↓         ↓       ↓        ↓
Event   Event   Event     Event   Event   Event
```

**Commands already built:**
- `/qa/pre-commit-qa` — QA checks
- `/devops/commit` — Conventional commits
- `/devops/push` — Push + CI wait
- `/review/fetch` — Get review comments
- `/workflow/merge-cycle` — Full orchestration

### Priority 5: Training Data & Public Development

**Goal:** Build reusable training data from development sessions.

**Approach:**
- Capture human-AI interactions as training examples
- Export successful workflows as templates
- Public "instructor development" — open development process

## Open Loops

| Item | Priority | Notes |
|------|----------|-------|
| Context tracking implementation | High | New events + projections |
| Tool usage backend | High | Hooks already capture, need projection |
| Docker workspace | Medium | Security considerations critical |
| Automated workflows | Medium | Commands exist, need orchestration polish |
| Training data export | Low | After observability is solid |

## Key Files

### Just Completed (Restructure)
- `lib/agentic-primitives/docs/adrs/021-primitives-directory-structure.md` — New standard
- `lib/agentic-primitives/primitives/v1/{commands,skills,agents}/` — Restructured
- `.claude/commands/{devops,qa,review,workflow}/` — New command categories

### For Context Tracking
- `packages/aef-domain/src/aef_domain/session/` — Session aggregate
- `packages/aef-adapters/src/aef_adapters/agents/` — Agent adapters

### For Tool Tracking
- `.claude/hooks/handlers/pre-tool-use.py` — Tool interception
- `.claude/hooks/handlers/post-tool-use.py` — Result capture

## Commands Reference

```bash
# Development
just dev                    # Start Docker stack
just dashboard-backend      # API server (8000)
just dashboard-frontend     # React UI (5173)
just primitives-sync        # Sync from agentic-primitives

# Testing
just test                   # All tests
just qa                     # Full QA pipeline

# Primitives
cd lib/agentic-primitives
agentic-p validate primitives  # Validate all
agentic-p build --provider claude  # Build for Claude
```
