# ADR-036: Workspace Structure Convention

**Status:** Proposed
**Date:** 2025-12-21
**Deciders:** Neural, Claude
**Context:** Artifact passing between workflow phases failing due to inconsistent directory structure

---

## Context

Agents running in Syn137 workspaces were not consistently writing artifacts to the expected locations, causing:

1. **Artifact passing failures** - Phase 2 couldn't find Phase 1 outputs
2. **Template substitution failures** - `{{phase_id}}` placeholders remained unsubstituted
3. **Repository location confusion** - Agents cloned to random locations (`/workspace/output/`, `/workspace/repo/`, etc.)

### Root Cause Analysis

The previous structure had several issues:

```
/workspace/
├── inputs/          ← Ambiguous name (could be "user inputs")
├── artifacts/       ← Too generic (input? output? both?)
└── output/          ← Created ad-hoc, not documented
```

1. **Split ownership**: Prompt lived in `agentic-primitives`, directory creation in Syn137's setup script
2. **Ambiguous naming**: `artifacts/` didn't distinguish input from output
3. **No repo convention**: Agents chose arbitrary locations for git operations
4. **Weak instructions**: Prompt said "write to artifacts/" but competing phase prompts confused agents

---

## Decision

### Standardized Workspace Structure

```
/workspace/
├── artifacts/
│   ├── input/       ← Previous phase outputs (read-only, populated by framework)
│   └── output/      ← Current phase deliverables (agent writes here)
└── repos/           ← Clone repositories here (supports multiple repos)
```

### Key Principles

1. **Explicit input/output separation** - No ambiguity about data flow direction
2. **Single `artifacts/` parent** - All artifact-related paths grouped together
3. **Plural `repos/`** - Supports multi-repository workflows (fork + upstream, dependencies)
4. **Baked into Docker image** - Directories exist before agent starts
5. **Strong prompt language** - "MUST write to", "REQUIRED", with examples

### Ownership

| Component | Responsibility |
|-----------|---------------|
| `agentic-primitives` Dockerfile | Create directory structure at build time |
| `agentic-primitives` prompt | Document structure, provide explicit instructions |
| Syn137 WorkspaceService | Inject files to `artifacts/input/`, validate structure |
| Syn137 WorkflowExecutionEngine | Collect from `artifacts/output/`, inject to next phase |

---

## Implementation

### 1. Dockerfile (agentic-primitives)

```dockerfile
# Create workspace directories with explicit structure
RUN mkdir -p /workspace/artifacts/input \
    && mkdir -p /workspace/artifacts/output \
    && mkdir -p /workspace/repos \
    && chown -R agent:agent /workspace
```

### 2. Workspace Prompt (agentic-primitives)

The prompt provides conditional guidance based on task type:

#### Key Principle: What is the Deliverable?

| Task Type | Deliverable | `artifacts/output/` Contains |
|-----------|-------------|------------------------------|
| **Coding task** | Code on GitHub (commits, PR) | Summary of work done |
| **Non-coding task** | The artifact itself | Research, design, analysis, etc. |

#### For Coding Tasks

The prompt instructs:
1. Clone to `repos/`, create feature branch
2. Make changes, commit, push to GitHub
3. Create PR if needed
4. Write **summary** to `artifacts/output/` with commits, PR URL, executive summary

> "**The code on GitHub is the deliverable.** The artifact is your summary of what was done."

#### For Non-Coding Tasks

The prompt instructs:
1. Use `repos/` only for reference if needed
2. Write deliverable directly to `artifacts/output/`

> "Your deliverable is **the content you write to `artifacts/output/`**."

This conditional framing helps agents understand that:
- Coding tasks = push code, summarize in artifacts
- Everything else = artifacts ARE the deliverable

### 3. Syn137 Framework Updates

```python
# Inject previous phase outputs
files_to_inject = [
    (f"artifacts/input/{phase_id}.md", content.encode())
    for phase_id, content in previous_outputs.items()
]

# Collect current phase outputs
artifacts = await workspace.collect_files(
    patterns=["artifacts/output/**/*"],
)
```

---

## Alternatives Considered

### 1. Keep existing structure, just fix prompts
- **Rejected**: Root cause is structural ambiguity, not just prompt weakness
- Agents will continue to be confused by `artifacts/` vs `inputs/`

### 2. Use `input/` and `output/` at top level
```
/workspace/
├── input/
├── output/
└── repos/
```
- **Rejected**: Less clear hierarchy, `artifacts` grouping is useful

### 3. Single `repo/` directory
- **Rejected**: Doesn't support multi-repo workflows (fork + upstream)
- Better to have `repos/` plural with convention for primary

### 4. Framework creates directories dynamically
- **Rejected**: Creates race condition, directories should exist before agent starts
- Baking into Docker image is more reliable

---

## Consequences

### Positive

1. **Clear contract** - Agents know exactly where to read/write
2. **Self-documenting** - Directory names describe purpose
3. **Reliable artifact passing** - Framework collects from predictable location
4. **Multi-repo support** - Complex workflows supported
5. **Single source of truth** - Convention lives in `agentic-primitives`

### Negative

1. **Breaking change** - Existing workflows need prompt updates
2. **Rebuild required** - Docker image must be rebuilt
3. **Path changes** - Any hardcoded paths need updating

### Migration

1. Update `agentic-primitives` (Dockerfile + prompt)
2. Rebuild Docker image
3. Update Syn137 inject/collect paths
4. Update workflow prompts to reference new paths
5. Test end-to-end artifact passing

---

## Related ADRs

- [ADR-012: Artifact Storage](ADR-012-artifact-storage.md) - How artifacts are persisted
- [ADR-021: Isolated Workspace Architecture](ADR-021-isolated-workspace-architecture.md) - Docker isolation model
- [ADR-023: Workspace-First Execution Model](ADR-023-workspace-first-execution-model.md) - Execution lifecycle
- [ADR-024: Setup Phase Secrets](ADR-024-setup-phase-secrets.md) - How secrets are injected

---

## References

- Investigation session: 2025-12-21
- Issue: Phase 2 not finding Phase 1 artifacts
- Execution ID with 0 artifacts: `342a2edc-0f6a-4646-a392-d9e021eb5cae`
