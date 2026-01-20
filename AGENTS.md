---
description:
globs:
alwaysApply: true
---
# AEF System Overview

## 🎯 Core Value Proposition

**AEF provides two first-class capabilities:**

### 1. Orchestration
- Isolated Docker workspaces for agent execution
- Secure token handling via setup phase (ADR-024)
- GitHub App integration for git operations (short-lived tokens)
- Lifecycle management (create → execute → cleanup)
- Multi-phase workflow execution

### 2. Observability
- **Every agent event is captured** (tool use, tokens, costs, errors)
- Real-time streaming to dashboard
- Projections for aggregated metrics (session stats, tool usage)
- Historical playback and analysis

```
┌─────────────────────────────────────────────────────────────────────────┐
│                     AEF: Orchestration + Observability                  │
│                                                                         │
│  ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐     │
│  │  ORCHESTRATION  │───▶│   AGENT RUNS    │───▶│  OBSERVABILITY  │     │
│  │                 │    │                 │    │                 │     │
│  │ WorkspaceService│    │ Claude CLI      │    │ Events → Store  │     │
│  │ Setup Phase     │    │ in Docker       │    │ Projections     │     │
│  │ Lifecycle Mgmt  │    │ JSONL stdout    │    │ Dashboard       │     │
│  └─────────────────┘    └─────────────────┘    └─────────────────┘     │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

## Package Structure

```
packages/
├── aef-adapters/      ← Orchestration: WorkspaceService, DockerIsolationAdapter
│                        Observability: EventStore, Projections, Subscriptions
│                        Token Management: SetupPhaseSecrets, GitHub App integration
├── aef-domain/        ← Domain events, aggregates, ports
├── aef-collector/     ← Event ingestion API (receives agent events)
└── aef-shared/        ← Shared settings, configuration

lib/agentic-primitives/  ← Shared library (git submodule)
└── lib/python/
    ├── agentic_events/    ← Event recording/playback for testing
    ├── agentic_adapters/  ← Claude CLI/SDK integration
    └── agentic_isolation/ ← Workspace providers
```

## ⚠️ KEY CONCEPT: Containerized Agent Execution

**Claude CLI runs INSIDE Docker containers, not on the host.**

```
┌──────────────────┐     ┌─────────────────────────────────────────┐
│   AEF (Host)     │     │   Docker Container                      │
│                  │     │   (agentic-workspace-claude-cli)        │
│  WorkspaceService│────▶│                                         │
│  creates/manages │     │   /workspace/  ← mounted from host      │
│  setup phase ────┼────▶│   secrets      → setup git creds        │
│                  │     │   claude CLI   ← runs prompts here      │
│                  │◀────│   stdout       → JSONL events           │
│  captures events │     │                                         │
└──────────────────┘     └─────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────────┐
│                    OBSERVABILITY PIPELINE                       │
│                                                                 │
│  Events → Collector → EventStore → Projections → Dashboard     │
│                                                                 │
│  Every tool use, token count, cost, and error is captured      │
└─────────────────────────────────────────────────────────────────┘
```

### Key Points:

1. **Agent runs in container:** Isolated, secure, reproducible
2. **Setup phase secrets:** GitHub App tokens configured during setup, cleared before agent runs (ADR-024)
3. **Events stream from stdout:** Zero overhead, JSONL events captured externally
4. **Full observability:** Every event flows to dashboard in real-time
5. **Testing with recordings:** Replay events without API calls

### Token Security (Current Implementation - ADR-024)

**Setup Phase Secrets Pattern** (OpenAI Codex-inspired):

```
SETUP PHASE                      AGENT PHASE
(~30 seconds)                    (main execution)
┌───────────────────┐            ┌───────────────────┐
│ Secrets available │───────────▶│ Secrets cleared   │
│                   │            │                   │
│ • GitHub App token│            │ • Claude CLI runs │
│ • ANTHROPIC_API_KEY            │ • Uses git creds  │
│ • Configure git   │            │   (credential     │
│   credential      │            │   helper)         │
│   helper          │            │ • No raw tokens   │
│ • Authenticate gh │            │   in environment  │
└───────────────────┘            └───────────────────┘
```

**Key Security Features:**
- ✅ **GitHub App integration** - Short-lived tokens (1hr), repo-scoped permissions
- ✅ **Git credential helper** - Persists git access without exposing raw token
- ✅ **Secrets cleared** - Environment cleaned before agent execution
- ✅ **All code on GitHub** - GitHub App is the primary auth mechanism

**Future Enhancement (ADR-022 - On Hold):**
- Sidecar proxy pattern for zero-trust (when multi-tenant needed)
- Tokens never enter container, injected via Envoy proxy
- Egress proxy for network allowlist enforcement

## Common Tasks

### Run Agent in Container
```bash
# Via WorkspaceService (Python)
async with service.create_workspace(execution_id="test") as ws:
    result = await ws.execute(["claude", "-p", "Hello"])

# Via Docker Compose
cd lib/agentic-primitives/providers/workspaces/claude-cli
docker compose up
```

### Capture Recording
```bash
cd lib/agentic-primitives/providers/workspaces/claude-cli
PROMPT="Your prompt" TASK="task-slug" \
docker compose -f docker-compose.record.yaml up
# Recording saved to fixtures/recordings/
```

### Use Recording in Tests
```python
from agentic_events import load_recording

player = load_recording("simple-bash")
for event in player:
    print(event)
```

### Test Observability Pipeline with Recordings
```python
from aef_adapters.workspace_backends.recording import RecordingEventStreamAdapter

# Replay recording through full AEF pipeline (no API calls)
adapter = RecordingEventStreamAdapter("simple-bash")
service = WorkspaceService.create_test(event_stream=adapter)

async with service.create_workspace(execution_id="test") as ws:
    async for line in ws.stream(["claude", "-p", "test"]):
        # Events flow through collector → projections
        pass
    # Assert events appeared in dashboard/projections
```

## Testing Philosophy: Zero Defects in Manual Testing

**Goal:** Manual testing should find ZERO bugs. All bugs should be caught by automated tests first.

### Test Pyramid

```
         ┌─────────┐
         │  E2E    │  ← Real API calls (expensive, few)
         ├─────────┤
         │ Integ.  │  ← Recording playback (free, many)
         ├─────────┤
         │  Unit   │  ← Fast, parallel (pytest -m unit -n auto)
         └─────────┘
```

### Recording-Based Integration Tests

- **7 recordings** available in `lib/agentic-primitives/.../fixtures/recordings/`
- Use `RecordingEventStreamAdapter` to test full observability pipeline
- **No API tokens spent** - recordings replay agent events

### What to Test

| Area | What to Verify |
|------|----------------|
| **Orchestration** | Workspace creates, executes, cleans up |
| **Observability** | Events flow from agent → collector → projections → dashboard |
| **Token counting** | Session shows correct input/output tokens |
| **Cost tracking** | Total cost USD is accurate |
| **Tool use** | Each tool invocation is recorded |

## Test Infrastructure (ADR-034)

AEF supports three testing modes that can run simultaneously:

```
┌───────────────────────────────────────────────────────────────────────────┐
│                        LOCAL DEVELOPMENT                                  │
│                                                                           │
│   DEV STACK (just dev)              TEST STACK (just test-stack)         │
│   ├── TimescaleDB: 5432             ├── TimescaleDB: 15432               │
│   ├── EventStore: 50051             ├── EventStore: 55051                │
│   ├── Collector: 8080               ├── Collector: 18080                 │
│   ├── MinIO: 9000/9001              ├── MinIO: 19000/19001               │
│   └── Redis: 6379                   └── Redis: 16379                     │
│                                                                           │
│   Volumes: PERSISTENT               Volumes: NONE (ephemeral)            │
│   Network: aef-network              Network: aef-test-network            │
│                                                                           │
└───────────────────────────────────────────────────────────────────────────┘
```

### Running Tests

```bash
# Unit tests (no infrastructure needed, recording-based)
just test-unit

# Start ephemeral test infrastructure
just test-stack           # Start test stack (ports +10000)
just test-stack-down      # Stop and cleanup

# Integration tests (uses test-stack if running, else testcontainers)
just test-integration     # Run integration tests
just test-integration-full # start → test → cleanup
```

### Test Fixture Detection Pattern

Integration tests auto-detect infrastructure in this order:

1. **Environment variables** (`TEST_DATABASE_URL`) - CI override
2. **Test-stack running** (port 15432) - local continuous testing
3. **Testcontainers fallback** - hermetic CI environments

```python
from aef_tests.fixtures import test_infrastructure, db_pool

@pytest.mark.integration
async def test_events_stored(test_infrastructure, db_pool):
    # Automatically uses whichever infrastructure is available
    async with db_pool.acquire() as conn:
        count = await conn.fetchval("SELECT COUNT(*) FROM event_store.events")
```

---

# 🔄 RIPER-5 MODE: STRICT OPERATIONAL PROTOCOL
v2.0.5 - 20250810

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│             │     │             │     │             │     │             │     │             │
│  RESEARCH   │────▶│  INNOVATE   │────▶│    PLAN     │────▶│   EXECUTE   │────▶│   REVIEW    │
│             │     │             │     │             │     │             │     │             │
└─────────────┘     └─────────────┘     └─────────────┘     └─────────────┘     └─────────────┘
       ▲                                       │                  │                    │
       │                                       │                  │                    │
       └───────────────────────────────────────┘                  │                    │
                                                                  │                    │
                                                                  ▼                    │
                                                        ┌─────────────────┐            │
                                                        │  QA CHECKPOINT  │            │
                                                        │  - Lint/Format  │            │
                                                        │  - Type Check   │            │
                                                        │  - Run Tests    │            │
                                                        │  - Review Files │            │
                                                        │  - Commit Files │            │
                                                        └─────────────────┘            │
                                                                  │                    │
                                                                  └────────────────────┘
```

## Mode Transition Signals
Only transition modes when these exact signals are used:

```
ENTER RESEARCH MODE or ERM
ENTER INNOVATE MODE or EIM
ENTER PLAN MODE or EPM
ENTER EXECUTE MODE or EEM
ENTER REVIEW MODE or EQM
DIRECT EXECUTE MODE or DEM // Used to bypass the plan and go straight to execute mode
```

## Meta-Instruction
**BEGIN EVERY RESPONSE WITH YOUR CURRENT MODE IN BRACKETS.**
**Format:** `[MODE: MODE_NAME]`

## The RIPER-5 Modes

### MODE 1: RESEARCH
- **Purpose:** Information gathering ONLY
- **Permitted:** Reading files, asking questions, understanding code
- **Forbidden:** Suggestions, planning, implementation
- **Output:** `[MODE: RESEARCH]` + observations and questions

### MODE 2: INNOVATE
- **Purpose:** Brainstorming potential approaches
- **Permitted:** Discussing ideas, advantages/disadvantages
- **Forbidden:** Concrete planning, code writing
- **Output:** `[MODE: INNOVATE]` + possibilities and considerations

### MODE 3: PLAN
- **Purpose:** Creating technical specification
- **Permitted:** Detailed plans with file paths and changes
- **Forbidden:** Implementation or code writing
- **Required:** Create comprehensive `PROJECT-PLAN_YYYYMMDD_<TASK-NAME>.md` with milestones. The milestones should consist of tasks with empty checkboxes to be filled in when the task is complete. (NEVER Commit the PROJECT-PLANs)
- **Output:** `[MODE: PLAN]` + specifications and implementation details
- **ADRs** Any architecture decisions should be captured in an Architecture Decision Record in `/docs/adrs/`
- **Test Driven Development:** Always keep testing in mind and add tests first, then implement features. Thinking with testing in mind first, also created better software design because it's designed to be easily testable. "Testing code is as important as Production code."

### MODE 4: EXECUTE
- **Purpose:** Implementing the approved plan exactly
- **Permitted:** Implementing detailed plan tasks, running QA checkpoints
- **Forbidden:** Deviations from plan, creative additions
- **Required:** After each milestone, run QA checkpoint and commit changes
- **Output:** `[MODE: EXECUTE]` + implementation matching the plan
- During execute, please use TODO comments for things that can be improved or changed in the future and use "FIXME" comments for things that are breaking the app.

### MODE 5: REVIEW
- **Purpose:** Validate implementation against plan
- **Permitted:** Line-by-line comparison
- **Required:** Flag ANY deviation with `:warning: DEVIATION DETECTED: [description]`
- **Output:** `[MODE: REVIEW]` + comparison and verdict

## QA Checkpoint Process

After each milestone in EXECUTE mode:
1. Run linter with auto-formatting
2. Run type checks
3. Run tests
4. Review changes with git MCP server
5. Commit changes with conventional commit messages before moving to next milestone

**python** for python, you can run all of the checks together with `poetry run poe check-fix`

```bash
# Run all checks and auto-format code
python scripts/qa_checkpoint.py

# Run checks and commit using conventional commit format
python scripts/qa_checkpoint.py --commit "Complete Milestone X" --conventional-commit
```

## Git MCP Server for Clean Commits

Use the git MCP server to review files and make logical commits:

```
[MODE: EXECUTE]

Let's use the git MCP server to review files and make logical commits with commit lint based messages:
```

1. Review current status and changes:
```bash
mcp_git_git_status <repo_path>
mcp_git_git_diff_unstaged <repo_path>
```

2. Make logical commits using conventional commit format:
```bash
# Stage related files
mcp_git_git_add <repo_path> ["file1.py", "file2.py"]

DO NOT Commit anything. Provide the Git Commit message and let me commit.
```

### Conventional Commit Format

Format: `type(scope): description`

Types:
- `feat`: New features
- `fix`: Bug fixes
- `docs`: Documentation
- `style`: Formatting changes
- `refactor`: Code restructuring
- `test`: Test changes
- `chore`: Maintenance

### Files to Exclude
- Temporary files
- Draft project plans
- Build artifacts
- Cache files

## Critical Guidelines
- Never transition between modes without explicit permission
- Always declare current mode at the start of every response
- Follow the plan with 100% fidelity in EXECUTE mode
- Flag even the smallest deviation in REVIEW mode
- Return to PLAN mode if any implementation issue requires deviation
- Use conventional commit messages for all commits

---

## 🚫 CRITICAL: Scratch Documentation Policy

**ROOT-LEVEL MARKDOWN FILES ARE SCRATCH DOCUMENTS - DO NOT COMMIT**

### Rule
- ❌ **NEVER commit** root-level `.md` files like:
  - `*-SUMMARY.md` (e.g., `CI-FIX-SUMMARY.md`)
  - `*-PLAN.md` (e.g., `TEST-ENHANCEMENT-PLAN.md`)
  - `PROJECT-PLAN_*.md`
  - `START-HERE.md`
  - Any other scratch/working docs in root

### Why
These are temporary working documents used during development sessions. They clutter the repository and become stale quickly.

### Where to Commit Documentation
- ✅ `docs/` directory - Permanent, maintained documentation
- ✅ `docs/adrs/` - Architecture Decision Records
- ✅ `README.md` - Project overview (specific exceptions)
- ✅ Package-specific docs within package directories

### Cleanup
Before committing, always check:
```bash
git status
# If you see root-level .md files (other than README.md), remove them:
rm -f *-SUMMARY.md *-PLAN.md PROJECT-PLAN_*.md START-HERE.md
```

---

**Remember:** If it's not in `docs/`, it's probably scratch and shouldn't be committed!
