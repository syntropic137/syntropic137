# ADR-048: Workflows as Claude Code Commands

## Status

**Accepted** — 2026-03-17

## Context

Workflow phases previously used custom `prompt_template` fields with ad-hoc `{{variable}}` substitution. Users had to learn this custom format and hardcode prompts per-workflow, making every workflow a one-off. This created several problems:

1. **Cognitive overhead**: Each workflow had its own prompt structure with no shared conventions
2. **No reusability**: Changing *what* to work on required editing the workflow definition itself
3. **No input validation**: The system had no way to declare or validate expected inputs
4. **Dashboard UX**: The UI had hardcoded demo inputs (`{ topic: 'AI Agents' }`) because it didn't know what inputs a workflow expected

### The Claude Code Command Pattern

Claude Code commands are markdown files with metadata that define HOW to approach a category of work. The task (WHAT to work on) is injected at runtime via `$ARGUMENTS`. This separation makes commands reusable across different tasks.

## Decision

**Workflow phases follow the Claude Code command standard.** Each phase is a meta-prompt that defines HOW to approach a step, while the task (WHAT) is injected at runtime via `$ARGUMENTS`.

### 1. Input Declarations

Workflows declare their expected inputs in a new `inputs:` YAML section:

```yaml
inputs:
  - name: task
    description: "What to research (issue body, topic, etc.)"
    required: true
  - name: topic
    description: "Short topic label"
    required: false
    default: "general"
```

This maps to the domain `InputDeclaration` value object:
```python
class InputDeclaration(BaseModel):
    name: str
    description: str | None = None
    required: bool = True
    default: str | None = None
```

### 2. $ARGUMENTS Substitution

The `task` input is special: it is substituted for `$ARGUMENTS` in phase prompts. This follows the Claude Code convention where `$ARGUMENTS` represents the primary task.

```yaml
prompt_template: |
  You are a research assistant.

  ## Your Task
  $ARGUMENTS

  ## How to Approach This
  1. Identify key areas
  2. Gather context from {{topic}}
```

Named inputs (`{{variable}}`) and `$ARGUMENTS` coexist. The substitution order is:

1. Built-in variables: `{{execution_id}}`, `{{workflow_id}}`, `{{repo_url}}`
2. Named inputs: `{{key}}` → value from `inputs` dict
3. `$ARGUMENTS` → value of `task` field (also available as `inputs["task"]`)
4. Phase outputs: `{{phase-id}}` → previous phase artifact content

### 3. Per-Phase Extensions

Two new optional fields on `PhaseDefinition`:

- `argument_hint: str | None` — describes what `$ARGUMENTS` expects (e.g., `"[task-description]"`)
- `model: str | None` — per-phase model override (e.g., `"sonnet"`, `"opus"`)

### 4. API and CLI Surface

**API:** New `task` field on `ExecuteWorkflowRequest`:
```json
POST /api/v1/workflows/{id}/execute
{"task": "Investigate auth middleware", "inputs": {"topic": "auth"}}
```

**CLI:** New `--task` / `-t` flag on `syn workflow run`:
```bash
syn workflow run research-workflow-v2 --task "$(gh issue view 211 --json body -q .body)"
```

**Dashboard:** Dynamic input form generated from `input_declarations`, with a prominent task textarea.

### 5. Backward Compatibility

- `input_declarations` defaults to `[]` — existing workflows unchanged
- `argument_hint` and `model` default to `None` — existing phases unchanged
- `task` defaults to `None` — existing API calls unchanged
- `{{variable}}`-only prompts still work — `$ARGUMENTS` is additive
- Existing serialized events deserialize correctly (new fields have defaults)

### 6. Invocation Stays as `claude -p`

We continue using `claude -p <prompt>` for agent invocation rather than the Agent SDK. The Agent SDK lacks JSONL streaming output, which is required for our observability pipeline (event recording, token tracking, tool timeline).

## Consequences

### Good

- **Reusable workflows**: The same research workflow handles any topic — just change `--task`
- **Self-documenting**: `input_declarations` tell users and agents what a workflow expects
- **Dynamic UI**: Dashboard generates forms from declarations — no more hardcoded inputs
- **Claude Code alignment**: Follows the same `$ARGUMENTS` convention developers already know
- **GitHub integration**: `--task "$(gh issue view 42 --json body -q .body)"` pipes issue content directly

### Trade-offs

- Two substitution syntaxes coexist (`$ARGUMENTS` and `{{variable}}`) — necessary for backward compatibility
- Commands are inlined in workflow phases for now — a shared Command aggregate is a future iteration

### Future Work

- Shared Command aggregate: Commands stored independently and referenced by ID from phases
- Command marketplace: Users share and discover commands
- Input validation: Runtime validation of required inputs before execution starts

## Related

- ISS-211: Implementation issue
- ADR-044: CLI-First, Agent-Native Interface Design
- ADR-014: Workflow Execution Model
- ADR-024: Secure Token Injection (workspace setup phase)
