# Codex ↔ Claude In-Container Delegation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a workflow phase's primary agent (claude or codex) shell out one-shot to the *other* CLI mid-run, opt-in per phase, riding the existing base-skills-in-image mechanism.

**Architecture:** Delegation is not a hard-wired handoff. It needs three runtime preconditions in the phase's workspace: (1) both CLIs installed, (2) both auth credentials staged, (3) the delegation guidance present so the agent knows *how*. Today all three are unmet on the headless docker path. This plan: (1) commits codex into the committed `claude-cli` image; (2) bakes the `delegation` plugin (skills) into that image's base plugin set; (3) adds an opt-in `agent.allow_delegation` flag that, when true for a headless phase, stages *both* auths and surfaces a provider-aware delegation recipe to whichever harness runs — preserving today's single-provider isolation everywhere the flag is false.

**Delegation-guidance delivery (round-1 review fix):** the baked `/opt/agentic/plugins` reach headless claude only via `AGENTIC_PLUGIN_FLAGS` computed by the container *entrypoint*; production runs the agent via `docker exec`, whose claude command carries only per-workflow `--plugin-dir` flags — so baked skills are NOT guaranteed on the command line. Therefore delegation guidance is delivered through the injected `/workspace/CLAUDE.md` + `/workspace/AGENTS.md` (identical content; claude auto-loads CLAUDE.md, codex reads AGENTS.md), NOT via `--plugin-dir`. The baked SKILL.md remains a fuller reference the note points at.

> **Round-1 codex review addressed (2026-07-23):** CHANGES REQUESTED. Confirmed-good: integration points, event round-trip, `plugins/delegation` bakeability (has `.claude-plugin/plugin.json`), cross-repo ordering. Fixed below: delegation guidance now via CLAUDE.md/AGENTS.md not `--plugin-dir` (was critical); `_apply_phase_update` field-preservation added (Task B2b); mixed-driver example uses artifact handoff not shared-workspace reads (headless phases get separate workspaces); image build uses `scripts/build-provider.py` not raw `docker build`; `allow_delegation` rejected for `claude-interactive`; manifest version bump + image publish step; isolation wording corrected to "effective agent-auth exposure"; API-exposure decision recorded (YAML-only for now).

**Tech Stack:** Python 3.14 (uv, pyright strict, ruff), Pydantic v2 domain models + event sourcing (ESP), Docker (workspace images), pytest. Two repos, both git submodules we own: `agentic-primitives` (image + base skills) and `syntropic137` (schema, auth staging, tests).

## Global Constraints

- **No magic strings for domain values** — reuse `AgentProvider` (`syn_shared/agents.py`); the delegation flag is a typed `bool`.
- **Strict typing** — pyright strict, no `Any`; new fields fully typed.
- **Credentials never in argv/logs/events/commits** — codex auth stays a 0600 `~/.codex/auth.json`; claude creds stay env-only via `_build_agent_env`. Delegation only widens *which* of these two existing mechanisms fire for a phase; it introduces no new credential transport.
- **Default preserves isolation** — `allow_delegation` defaults `False`; when false, the *effective agent-auth exposure* is unchanged (a claude phase's agent gets no codex auth; a codex phase's agent gets no claude env). Note: claude creds are still *resolved* during setup for codex phases today but never retained in the agent env, so this is an effective-exposure guarantee, not literal setup-time isolation.
- **Delegation is headless-only** — `allow_delegation` is rejected for `provider: claude-interactive` (the tmux path has a different image/auth model that this plan does not verify). Enforced in `AgentYamlDefinition` validation.
- **Fix all instances of a field-threading change together** — `AgentConfiguration` exists in TWO modules (`_shared/ExecutionValueObjects.py` and `aggregate_execution/value_objects.py`); both must carry `allow_delegation`.
- **No em dashes in any file** — use hyphens.
- **Exact dep pins** — `@openai/codex` pinned to `0.144.6` (matches the running local image).
- **Both submodules get their own branch + PR** — never push the submodule pointer bump before the agentic-primitives PR merges.

---

## File Structure

**Repo A — `agentic-primitives`** (produces a new workspace image):
- Modify `providers/workspaces/claude-cli/Dockerfile` — install codex CLI alongside claude; add codex to the verify line.
- Modify `providers/workspaces/claude-cli/manifest.yaml` — add `delegation` to `plugins.include`.
- Possibly add `plugins/delegation/plugin.yaml` (or marketplace entry) if the bake step requires plugin metadata (verified in Task A2).

**Repo B — `syntropic137`** (schema + auth staging + surfacing + tests):
- `packages/syn-domain/.../_shared/workflow_definition.py` — `AgentYamlDefinition.allow_delegation` + thread through `PhaseYamlDefinition.to_domain`.
- `packages/syn-domain/.../aggregate_workflow_template/value_objects.py` — `PhaseDefinition.allow_delegation`.
- `packages/syn-domain/.../_shared/ExecutionValueObjects.py` AND `.../aggregate_execution/value_objects.py` — `AgentConfiguration.allow_delegation` (both copies).
- `packages/syn-domain/.../execute_workflow/ExecuteWorkflowHandler.py` — carry `allow_delegation` in `_build_agent_config_from_phase`.
- `packages/syn-domain/.../execute_workflow/handlers/WorkspaceProvisionHandler.py` — both-auth staging + codex-facing delegation note in AGENTS.md.
- `workflows/examples/` — a mixed-driver example + a delegating-codex example.
- Tests co-located per slice (`test_*.py`).

Each task ends with an independently testable deliverable.

---

## PART A — agentic-primitives (image + base skills)

### Task A1: Commit codex CLI into the claude-cli image

**Files:**
- Modify: `lib/agentic-primitives/providers/workspaces/claude-cli/Dockerfile` (near line 41 for the ARG, line 98 for the install, and the final verify/label region ~249)

**Interfaces:**
- Produces: a committed image `agentic-workspace-claude-cli` with both `claude` and `codex` on PATH (the running local image already has this at codex 0.144.6; this makes it reproducible).

- [ ] **Step 1: Add the codex version ARG next to the claude ARG**

At the top ARG block (near `ARG CLAUDE_CLI_VERSION=2.1.126`, line 41):

```dockerfile
ARG CLAUDE_CLI_VERSION=2.1.126
ARG CODEX_CLI_VERSION=0.144.6
```

- [ ] **Step 2: Install codex right after the claude install (line ~97-98)**

```dockerfile
ARG CLAUDE_CLI_VERSION
RUN npm install -g @anthropic-ai/claude-code@${CLAUDE_CLI_VERSION}
ARG CODEX_CLI_VERSION
RUN npm install -g @openai/codex@${CODEX_CLI_VERSION}
```

- [ ] **Step 3: Verify both CLIs in the same build layer (add to an existing verify RUN or add one)**

```dockerfile
RUN claude --version && codex --version
```

- [ ] **Step 4: Add the codex version label next to the claude label (~line 250)**

```dockerfile
ARG CODEX_CLI_VERSION
LABEL agentic.codex_cli_version=${CODEX_CLI_VERSION}
```

- [ ] **Step 5: Build via the provider builder and verify (per feedback_local_build_before_base_bump)**

The Dockerfile is NOT built from `providers/workspaces/claude-cli/` directly — its context needs staged `packages/`, `plugins/`, `scripts/`, `memory/`. Use the repo's builder:
```bash
cd lib/agentic-primitives
uv run scripts/build-provider.py claude-cli --tag agentic-workspace-claude-cli:delegation-test
docker run --rm --entrypoint sh agentic-workspace-claude-cli:delegation-test -lc 'claude --version && codex --version'
```
Expected: prints `2.1.126 (Claude Code)` and `codex-cli 0.144.6`.

- [ ] **Step 6: Commit** (on an `agentic-primitives` feature branch)

```bash
git add providers/workspaces/claude-cli/Dockerfile
git commit -m "feat(claude-cli): install codex CLI alongside claude for delegation"
```

### Task A2: Bake the `delegation` plugin into the base skill set

**Files:**
- Modify: `lib/agentic-primitives/providers/workspaces/claude-cli/manifest.yaml` (the `plugins.include` list, ~line 35-38)
- Possibly create: `lib/agentic-primitives/plugins/delegation/plugin.yaml` (only if the bake step requires it — verified in Step 2)

**Interfaces:**
- Produces: `/opt/agentic/plugins/delegation/skills/{delegating-to-codex,delegating-to-claude-p}/SKILL.md` present in the image, discoverable by claude via `--plugin-dir /opt/agentic`.

- [ ] **Step 1: Add `delegation` to the include list AND bump the manifest version**

The manifest's `version:` (currently `"1.1.1"`, line 7) identifies image contents; adding codex + a baked plugin is a feature change, so bump it:
```yaml
version: "1.2.0"
```
```yaml
plugins:
  include:
    - sdlc
    - workspace
    - observability
    - delegation
```

- [ ] **Step 2: Verify the delegation plugin is bakeable**

Run (from `lib/agentic-primitives`):
```bash
ls plugins/delegation/skills/delegating-to-codex/SKILL.md plugins/delegation/skills/delegating-to-claude-p/SKILL.md
# Compare structure to an already-baked plugin:
ls plugins/sdlc/ && ls plugins/delegation/
```
Expected: both SKILL.md files exist. If `plugins/sdlc/` has a `plugin.yaml`/`marketplace.json` that `plugins/delegation/` lacks, create the equivalent minimal metadata file for `delegation` so the manifest bake resolves it. (README + skills-only may be sufficient - confirm by the build in Step 3.)

- [ ] **Step 3: Rebuild the image and verify the skill baked in**

```bash
cd lib/agentic-primitives
uv run scripts/build-provider.py claude-cli --tag agentic-workspace-claude-cli:delegation-test
docker run --rm --entrypoint sh agentic-workspace-claude-cli:delegation-test -lc \
  'ls /opt/agentic/plugins/delegation/skills/delegating-to-claude-p/SKILL.md /opt/agentic/plugins/delegation/skills/delegating-to-codex/SKILL.md'
```
Expected: both paths listed (exist).

- [ ] **Step 4: Commit + publish the image the stack consumes**

```bash
git add providers/workspaces/claude-cli/manifest.yaml plugins/delegation/
git commit -m "feat(claude-cli): bake delegation skills into the base plugin set (v1.2.0)"
```
A submodule pointer bump alone does NOT update an already-built runtime image. Retag/publish the image the dev stack resolves (`agentic-workspace-claude-cli:latest`) and, before B6, verify the running workspace image ID/labels include `agentic.codex_cli_version=0.144.6` and the delegation skill:
```bash
docker tag agentic-workspace-claude-cli:delegation-test agentic-workspace-claude-cli:latest
docker inspect agentic-workspace-claude-cli:latest --format '{{index .Config.Labels "agentic.codex_cli_version"}}'
```

---

## PART B — syntropic137 (schema, staging, surfacing, tests)

> All paths below are relative to the `syntropic137` repo root. Work on branch `feat/codex-claude-delegation` (already created off `feat/codex-bridge`).

### Task B1: Add `allow_delegation` to the YAML schema + thread to the domain phase

**Files:**
- Modify: `packages/syn-domain/src/syn_domain/contexts/orchestration/_shared/workflow_definition.py` (`AgentYamlDefinition` ~line 182-194; `PhaseYamlDefinition.to_domain` ~line 264-302)
- Modify: `packages/syn-domain/src/syn_domain/contexts/orchestration/domain/aggregate_workflow_template/value_objects.py` (`PhaseDefinition` ~line 120, after `agent_id`)
- Test: `packages/syn-domain/src/syn_domain/contexts/orchestration/_shared/test_workflow_definition.py` (co-located; create if absent)

**Interfaces:**
- Produces: `AgentYamlDefinition.allow_delegation: bool = False`; `PhaseDefinition.allow_delegation: bool = False`; `to_domain()` copies the flag through.
- Consumes: nothing new.

- [ ] **Step 1: Write the failing test**

```python
# in test_workflow_definition.py
from syn_domain.contexts.orchestration._shared.workflow_definition import WorkflowDefinition

_YAML = """
id: deleg-test
name: Delegation Test
type: research
classification: simple
requires_repos: false
phases:
  - id: p1
    name: Codex with delegation
    order: 1
    prompt_template: do the thing
    agent:
      provider: codex
      allow_delegation: true
"""

def test_allow_delegation_flows_to_domain_phase() -> None:
    defn = WorkflowDefinition.from_yaml(_YAML)
    phase = defn.get_domain_phases()[0]
    assert phase.provider == "codex"
    assert phase.allow_delegation is True

def test_allow_delegation_defaults_false() -> None:
    yaml = _YAML.replace("      allow_delegation: true\n", "")
    phase = WorkflowDefinition.from_yaml(yaml).get_domain_phases()[0]
    assert phase.allow_delegation is False
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest packages/syn-domain/src/syn_domain/contexts/orchestration/_shared/test_workflow_definition.py -k allow_delegation -v`
Expected: FAIL (`AgentYamlDefinition` rejects unknown `allow_delegation` under `extra="forbid"`, or `PhaseDefinition` has no such attr).

- [ ] **Step 3: Add the field to `AgentYamlDefinition`** (after `model`, ~line 193)

```python
    model: str | None = None
    """Per-phase model override (e.g. ``sonnet``, ``opus``)."""

    allow_delegation: bool = False
    """When true, stage BOTH agent auths in this phase's workspace so the
    primary agent can shell out one-shot to the other CLI (codex -> ``claude
    -p`` or claude -> ``codex exec``). Headless providers only. Default false
    preserves single-provider isolation. See
    docs/superpowers/plans/2026-07-23-codex-claude-delegation.md."""
```

- [ ] **Step 3b: Reject `allow_delegation` on the interactive path (extend the validator)**

In `_validate_provider_agent_combo` (the existing `@model_validator(mode="after")` on `AgentYamlDefinition`), add:

```python
        if self.allow_delegation and self.provider == AgentProvider.CLAUDE_INTERACTIVE:
            msg = (
                "agent.allow_delegation is only supported on the headless "
                "providers ('claude', 'codex'); the interactive-tmux path has a "
                "different image/auth model. Remove allow_delegation or switch provider."
            )
            raise ValueError(msg)
        return self
```

Add a test:
```python
def test_allow_delegation_rejected_for_interactive() -> None:
    import pytest
    yaml = _YAML.replace("provider: codex", "provider: claude-interactive")
    with pytest.raises(ValueError, match="headless"):
        WorkflowDefinition.from_yaml(yaml)
```

- [ ] **Step 4: Add the field to `PhaseDefinition`** (`aggregate_workflow_template/value_objects.py`, after `agent_id`, ~line 120)

```python
    allow_delegation: bool = False
    """When true, both agent auths are staged so the phase's primary agent can
    delegate one-shot to the other CLI. Sourced from ``agent.allow_delegation``."""
```

- [ ] **Step 5: Thread through `to_domain`** (`PhaseYamlDefinition.to_domain`, ~line 282-302)

Add alongside the existing `provider`/`agent_id` extraction and pass into the `PhaseDefinition(...)` constructor:

```python
        provider = self.agent.provider if self.agent else None
        agent_id = self.agent.agent_id if self.agent else None
        agent_model = self.agent.model if self.agent else None
        allow_delegation = self.agent.allow_delegation if self.agent else False
        model = self.model or agent_model

        return PhaseDefinition(
            ...
            model=model,
            provider=provider,
            agent_id=agent_id,
            allow_delegation=allow_delegation,
        )
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest packages/syn-domain/src/syn_domain/contexts/orchestration/_shared/test_workflow_definition.py -k allow_delegation -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add packages/syn-domain/src/syn_domain/contexts/orchestration/_shared/workflow_definition.py \
        packages/syn-domain/src/syn_domain/contexts/orchestration/domain/aggregate_workflow_template/value_objects.py \
        packages/syn-domain/src/syn_domain/contexts/orchestration/_shared/test_workflow_definition.py
git commit -m "feat(workflows): add agent.allow_delegation phase flag (schema + domain phase)"
```

### Task B2: Carry `allow_delegation` into AgentConfiguration (both copies) + execution

**Files:**
- Modify: `packages/syn-domain/src/syn_domain/contexts/orchestration/_shared/ExecutionValueObjects.py` (`AgentConfiguration` ~line 32, after `agent_id`)
- Modify: `packages/syn-domain/src/syn_domain/contexts/orchestration/domain/aggregate_execution/value_objects.py` (`AgentConfiguration` ~line 53)
- Modify: `packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/ExecuteWorkflowHandler.py` (`_build_agent_config_from_phase` ~line 149-167)
- Test: `packages/syn-domain/.../slices/execute_workflow/` existing handler test or a new focused test.

**Interfaces:**
- Consumes: `PhaseDefinition.allow_delegation` (Task B1).
- Produces: `AgentConfiguration.allow_delegation: bool = False` on both classes; `_build_agent_config_from_phase` copies `phase.allow_delegation` into it.

- [ ] **Step 1: Write the failing test**

```python
# focused test near ExecuteWorkflowHandler tests
from syn_domain.contexts.orchestration.slices.execute_workflow.ExecuteWorkflowHandler import (
    _build_agent_config_from_phase,
)
from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.value_objects import (
    PhaseDefinition,
)

def test_agent_config_carries_allow_delegation() -> None:
    phase = PhaseDefinition(
        phase_id="p1", name="p", order=1, prompt_template="x",
        provider="codex", allow_delegation=True,
    )
    cfg = _build_agent_config_from_phase(phase)
    assert cfg.provider == "codex"
    assert cfg.allow_delegation is True
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest <that test file> -k allow_delegation -v`
Expected: FAIL (`AgentConfiguration` has no `allow_delegation`).

- [ ] **Step 3: Add the field to BOTH `AgentConfiguration` classes** (after `agent_id`)

```python
    allow_delegation: bool = False
    # When true, both agent auths are staged so this phase's primary agent may
    # delegate one-shot to the other CLI. Default false = single-provider isolation.
```

- [ ] **Step 4: Copy it through `_build_agent_config_from_phase`** (ExecuteWorkflowHandler.py ~line 158-167)

```python
    phase_model: str | None = getattr(phase, "model", None)
    phase_provider: str | None = getattr(phase, "provider", None)
    phase_agent_id: str | None = getattr(phase, "agent_id", None)
    allow_delegation: bool = bool(getattr(phase, "allow_delegation", False))
    if not (phase_model or phase_provider or phase_agent_id or allow_delegation):
        return AgentConfiguration()
    defaults = AgentConfiguration()
    return AgentConfiguration(
        provider=phase_provider or defaults.provider,
        model=phase_model or defaults.model,
        agent_id=phase_agent_id or defaults.agent_id,
        allow_delegation=allow_delegation,
    )
```

- [ ] **Step 5: Verify `ExecutablePhase` construction preserves the config**

`_build_executable_phases` (ExecuteWorkflowHandler ~line 305-325) already passes the whole `agent_config` into `ExecutablePhase(agent_config=...)`, so `allow_delegation` rides along - no change needed. Confirm by grep: `agent_config=agent_config`.

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest <that test file> -k allow_delegation -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add packages/syn-domain/src/syn_domain/contexts/orchestration/_shared/ExecutionValueObjects.py \
        packages/syn-domain/src/syn_domain/contexts/orchestration/domain/aggregate_execution/value_objects.py \
        packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/ExecuteWorkflowHandler.py \
        <the test file>
git commit -m "feat(execution): carry allow_delegation into AgentConfiguration"
```

### Task B2b: Stop phase-update from wiping provider/agent_id/allow_delegation

**Files:**
- Modify: `packages/syn-domain/src/syn_domain/contexts/orchestration/domain/aggregate_workflow_template/WorkflowTemplateAggregate.py` (`_apply_phase_update`)
- Test: `packages/syn-domain/.../slices/update_workflow_phase/test_update_workflow_phase.py`

**Interfaces:** none new — fixes a latent bug: `_apply_phase_update` reconstructs `PhaseDefinition` from scratch and currently omits `provider`, `agent_id`, and (after B1) `allow_delegation`, so any prompt/model edit silently resets them. (The `feat/dashboard-provider-selector` branch already preserves provider/agent_id; this branch is off `feat/codex-bridge` and does not have that fix, so it is included here for `allow_delegation` and the two others. On merge, keep the superset that preserves all four fields.)

- [ ] **Step 1: Write the failing test**

```python
def test_prompt_update_preserves_provider_agentid_and_delegation() -> None:
    from syn_shared.agents import AgentProvider
    agg = WorkflowTemplateAggregate()
    agg._handle_command(CreateWorkflowTemplateCommand(
        aggregate_id="w1", name="W", workflow_type=WorkflowType.RESEARCH,
        classification=WorkflowClassification.SIMPLE, repository_url="", repository_ref="main",
        phases=[PhaseDefinition(
            phase_id="p1", name="p", order=1, prompt_template="orig",
            provider=AgentProvider.CODEX, allow_delegation=True,
        )],
    ))
    agg.mark_events_as_committed()
    agg._handle_command(UpdatePhasePromptCommand(
        aggregate_id="w1", phase_id="p1", prompt_template="new",
    ))
    p = next(x for x in agg.phases if x.phase_id == "p1")
    assert p.provider == AgentProvider.CODEX
    assert p.allow_delegation is True
    assert p.prompt_template == "new"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest packages/syn-domain/src/syn_domain/contexts/orchestration/slices/update_workflow_phase/test_update_workflow_phase.py -k preserves_provider -v`
Expected: FAIL (`provider` resets to `None`/claude default).

- [ ] **Step 3: Preserve the fields in `_apply_phase_update`**

In the `return PhaseDefinition(...)` inside `_apply_phase_update`, add:
```python
        model=_coalesce(data["model"], phase.model),
        provider=phase.provider,
        agent_id=phase.agent_id,
        allow_delegation=phase.allow_delegation,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: same as Step 2. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/syn-domain/.../WorkflowTemplateAggregate.py packages/syn-domain/.../update_workflow_phase/test_update_workflow_phase.py
git commit -m "fix(workflows): preserve provider/agent_id/allow_delegation on phase update"
```

### Task B3: Stage BOTH auths when a phase allows delegation

**Files:**
- Modify: `packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/handlers/WorkspaceProvisionHandler.py` (the `include_codex_auth=` call ~line 338, and `needs_claude_env =` ~line 492)
- Test: co-located `test_*.py` for WorkspaceProvisionHandler (create a focused unit test if none covers this).

**Interfaces:**
- Consumes: `phase.agent_config.allow_delegation` (Task B2).
- Produces: when `allow_delegation` is true, `include_codex_auth` is true AND `needs_claude_env` is true regardless of provider; when false, behavior is unchanged.

- [ ] **Step 1: Write the failing test** (pure boolean-logic test of the two conditions; extract them into a tiny helper to make them testable)

Add a module-level helper and test it:

```python
# helper in WorkspaceProvisionHandler.py
def _auth_staging_for(provider: str, allow_delegation: bool, is_interactive: bool) -> tuple[bool, bool]:
    """Return (include_codex_auth, needs_claude_env) for a phase.

    Delegation opt-in stages BOTH; otherwise auth is scoped to the phase's
    single provider (codex file for codex phases, claude env otherwise).
    """
    include_codex_auth = allow_delegation or provider == AgentProvider.CODEX
    needs_claude_env = not is_interactive and (allow_delegation or provider != AgentProvider.CODEX)
    return include_codex_auth, needs_claude_env
```

```python
# test
from syn_domain.contexts.orchestration.slices.execute_workflow.handlers.WorkspaceProvisionHandler import (
    _auth_staging_for,
)
from syn_shared.agents import AgentProvider

def test_codex_phase_no_delegation_stages_codex_only() -> None:
    assert _auth_staging_for(AgentProvider.CODEX, False, False) == (True, False)

def test_claude_phase_no_delegation_stages_claude_only() -> None:
    assert _auth_staging_for(AgentProvider.CLAUDE, False, False) == (False, True)

def test_delegation_stages_both_regardless_of_provider() -> None:
    assert _auth_staging_for(AgentProvider.CODEX, True, False) == (True, True)
    assert _auth_staging_for(AgentProvider.CLAUDE, True, False) == (True, True)

def test_interactive_never_needs_claude_env() -> None:
    assert _auth_staging_for(AgentProvider.CLAUDE, True, True)[1] is False
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest <WorkspaceProvisionHandler test> -k auth_staging -v`
Expected: FAIL (`_auth_staging_for` not defined).

- [ ] **Step 3: Add the helper and use it at both call sites**

At the `_hydrate_workspace` call (~line 335-340):
```python
            include_codex_auth, _ = _auth_staging_for(
                phase.agent_config.provider,
                phase.agent_config.allow_delegation,
                is_interactive=False,
            )
            await self._hydrate_workspace(
                workspace, effective_repos, include_codex_auth=include_codex_auth,
            )
```

At the `needs_claude_env` line (~line 492):
```python
        _, needs_claude_env = _auth_staging_for(
            phase.agent_config.provider,
            phase.agent_config.allow_delegation,
            is_interactive=is_interactive,
        )
        agent_env = await _build_agent_env(workspace, session_id) if needs_claude_env else {}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest <WorkspaceProvisionHandler test> -k auth_staging -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/handlers/WorkspaceProvisionHandler.py <test file>
git commit -m "feat(provisioning): stage both auths for delegation-enabled phases"
```

### Task B4: Surface delegation guidance to a codex-primary phase (AGENTS.md)

**Files:**
- Modify: `packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/handlers/WorkspaceProvisionHandler.py` (the AGENTS.md inject path ~line 381-391 and `_generate_workspace_context` ~line 561)
- Test: same handler test file.

**Interfaces:**
- Consumes: `phase.agent_config.allow_delegation` + `provider`.
- Produces: `_delegation_note(provider, allow_delegation)` returns a recipe for the OTHER CLI, appended to the shared `/workspace/CLAUDE.md` + `/workspace/AGENTS.md` content. Claude auto-loads CLAUDE.md and codex reads AGENTS.md, so the primary agent gets its delegation recipe regardless of `--plugin-dir` delivery. Both directions covered: a codex-primary phase learns to `claude -p`; a claude-primary phase learns to `codex exec`.

- [ ] **Step 1: Write the failing test**

```python
def test_delegation_note_codex_primary_targets_claude() -> None:
    note = WorkspaceProvisionHandler._delegation_note("codex", True)
    assert "claude -p" in note and "delegating-to-claude-p" in note

def test_delegation_note_claude_primary_targets_codex() -> None:
    note = WorkspaceProvisionHandler._delegation_note("claude", True)
    assert "codex exec" in note and "delegating-to-codex" in note

def test_no_delegation_note_when_disabled() -> None:
    assert WorkspaceProvisionHandler._delegation_note("codex", False) == ""
    assert WorkspaceProvisionHandler._delegation_note("claude", False) == ""
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest <handler test> -k delegation_note -v`
Expected: FAIL (`_delegation_note` undefined).

- [ ] **Step 3: Add the provider-aware `_delegation_note` staticmethod**

```python
    @staticmethod
    def _delegation_note(provider: str, allow_delegation: bool) -> str:
        """Delegation recipe for the phase's primary agent, targeting the OTHER
        CLI. Appended to the injected /workspace/CLAUDE.md + AGENTS.md so it
        reaches whichever harness runs (claude reads CLAUDE.md, codex reads
        AGENTS.md) - independent of --plugin-dir/entrypoint plugin discovery.
        """
        if not allow_delegation:
            return ""
        if provider == AgentProvider.CODEX:
            return (
                "\n## Delegation available\n"
                "You may delegate a subtask one-shot to Claude Code (both auths are\n"
                "staged here). Fuller guide: /opt/agentic/plugins/delegation/skills/"
                "delegating-to-claude-p/SKILL.md.\n"
                "Recipe: `claude -p --permission-mode bypassPermissions "
                "--output-format stream-json --verbose \"<task>\"`.\n"
            )
        # headless claude primary (provider claude); interactive is rejected in B1
        return (
            "\n## Delegation available\n"
            "You may delegate a subtask one-shot to OpenAI Codex (both auths are\n"
            "staged here). Fuller guide: /opt/agentic/plugins/delegation/skills/"
            "delegating-to-codex/SKILL.md.\n"
            "Recipe: `codex exec --full-auto --json --skip-git-repo-check \"<task>\"`.\n"
        )
```

- [ ] **Step 4: Append the note where the workspace context is generated**

At the AGENTS.md/CLAUDE.md inject site (~line 381-391), append the note to the shared `context` before writing both files:

```python
        context = self._generate_workspace_context(effective_repos)
        context += self._delegation_note(
            phase.agent_config.provider, phase.agent_config.allow_delegation
        )
        # existing write: [("AGENTS.md", context.encode()), ("CLAUDE.md", context.encode())]
```
Both files get identical content (as today); a non-delegating phase gets an empty note, so behavior is unchanged when the flag is off.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest <handler test> -k delegation_note -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add packages/syn-domain/.../WorkspaceProvisionHandler.py <test file>
git commit -m "feat(provisioning): surface delegation recipe to codex phases via AGENTS.md"
```

### Task B5: Example workflows + regenerate + local unit gate

**Files:**
- Create: `workflows/examples/multi-agent-programmatic.yaml` (phase 1 `provider: claude`, phase 2 `provider: codex`, shared workspace - the mixed-driver proof)
- Create: `workflows/examples/codex-delegates-to-claude.yaml` (single codex phase, `allow_delegation: true`, prompt instructs a `claude -p` delegation)
- Modify: none generated (schema change adds an optional field; run `just codegen` only if any API response model surfaces `allow_delegation` - it does not in this plan).

**Interfaces:** none (author-facing examples).

- [ ] **Step 1: Write `multi-agent-programmatic.yaml`** (artifact-mediated handoff — headless phases get SEPARATE workspaces, so phase 2 consumes phase 1's output as an injected input artifact, NOT a shared file)

```yaml
id: multi-agent-programmatic
name: Multi-agent (claude plans, codex implements)
description: Phase 1 runs the claude driver and emits a plan artifact; phase 2 runs the codex driver and consumes it as an injected input artifact (separate workspaces, artifact-mediated handoff).
type: research
classification: simple
requires_repos: false
phases:
  - id: plan
    name: Plan (claude)
    order: 1
    execution_type: sequential
    input_artifacts: []
    output_artifacts:
      - text
    max_tokens: 2048
    timeout_seconds: 300
    agent:
      provider: claude
    prompt_template: |
      Write a one-paragraph plan for a palindrome checker to
      /workspace/artifacts/output/plan.md, then print the plan.
  - id: implement
    name: Implement (codex)
    order: 2
    execution_type: sequential
    input_artifacts:
      - text
    output_artifacts:
      - text
    max_tokens: 4096
    timeout_seconds: 600
    agent:
      provider: codex
    prompt_template: |
      Read the plan artifact injected from the previous phase under
      /workspace/artifacts/input/ (the plan.md this workflow's phase 1
      produced), implement palindrome.py with tests, run them, and print a
      one-line result.
```

Note: confirm the exact injected input path during Step 3 (the artifact collector's `inject_from_previous_phases_explicit` decides it); adjust the prompt wording to the real path if it differs from `/workspace/artifacts/input/`.

- [ ] **Step 2: Write `codex-delegates-to-claude.yaml`**

```yaml
id: codex-delegates-to-claude
name: Codex delegates a subtask to Claude
description: A codex-primary phase that shells out to `claude -p` one-shot.
type: research
classification: simple
requires_repos: false
phases:
  - id: build-and-delegate
    name: Codex builds, delegates review to Claude
    order: 1
    execution_type: sequential
    max_tokens: 4096
    timeout_seconds: 600
    agent:
      provider: codex
      allow_delegation: true
    prompt_template: |
      Implement palindrome.py with is_palindrome(s: str) -> bool. Then delegate a
      code review to Claude Code with one shell command:
      `claude -p --permission-mode bypassPermissions --output-format stream-json
      --verbose "Review /workspace/palindrome.py for correctness; reply with a
      one-line verdict"`. Print Claude's verdict, then a one-line summary.
```

- [ ] **Step 3: Validate both load against the schema**

Run:
```bash
uv run python -c "
from pathlib import Path
from syn_domain.contexts.orchestration._shared.workflow_definition import WorkflowDefinition
for f in ('multi-agent-programmatic','codex-delegates-to-claude'):
    d = WorkflowDefinition.from_file(Path(f'workflows/examples/{f}.yaml'))
    ph = d.get_domain_phases()
    print(f, [(p.provider, p.allow_delegation) for p in ph])
"
```
Expected: `multi-agent-programmatic [('claude', False), ('codex', False)]` and `codex-delegates-to-claude [('codex', True)]`.

- [ ] **Step 4: Run the full local gate**

Run:
```bash
uv run ruff check . && uv run ruff format --check .
uv run pyright packages/syn-domain apps/syn-api
uv run pytest packages/syn-domain/src/syn_domain/contexts/orchestration -q
just fitness-check
```
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add workflows/examples/multi-agent-programmatic.yaml workflows/examples/codex-delegates-to-claude.yaml
git commit -m "docs(examples): programmatic mixed-driver + codex-delegates-to-claude workflows"
```

### Task B6: Live e2e on the codex stack (:9137)

**Files:** none (verification task).

**Interfaces:** Consumes the new image (Part A, retagged `:latest`) + all of Part B.

- [ ] **Step 1: Rebuild syn-api from this branch and confirm the delegation image is used**

Rebuild the `syn-*` dev stack api from `feat/codex-claude-delegation` (SYN_INSTALL_DIR=<this worktree>, SYN_WORKSPACE_DOCKER_NETWORK=syn-dev_agent-net, CODEX_AUTH_JSON set, CLAUDE_CODE_OAUTH_TOKEN set). Verify the workspace image tag resolves to the codex+delegation `agentic-workspace-claude-cli:latest`.

- [ ] **Step 2: Register + run the delegation workflow via :9137**

```bash
PW="${SYN_API_PASSWORD:-admin}"; BASE=http://localhost:9137
curl -s -u "admin:$PW" -X POST "$BASE/api/v1/workflows/from-yaml" \
  -H "content-type: application/x-yaml" \
  --data-binary @workflows/examples/codex-delegates-to-claude.yaml
curl -s -u "admin:$PW" -X POST "$BASE/api/v1/workflows/codex-delegates-to-claude/execute" \
  -H "content-type: application/json" -d '{}'
```

- [ ] **Step 3: Verify the delegation happened and is observable**

Poll to `completed`, then fetch the session_log (MinIO `syn-conversations/sessions/{sid}/conversation.jsonl`) and confirm a `command_execution` item whose command starts with `claude` (the delegated sub-run), plus a non-empty Claude verdict in the codex `agent_message`. Run the observability harness against the session and confirm all metrics reconcile:
```bash
uv run python scripts/validate_codex_observability.py --session <sid> --base-url http://localhost:9137
```
Expected: the delegated `claude -p` run appears as a Bash `command_execution` in the codex `--json` stream (delegation observability is free), and the harness reports PASS on the recorded metrics.

- [ ] **Step 4: Run the mixed-driver workflow too**

Register + run `multi-agent-programmatic.yaml`; confirm phase 1 streams as a claude phase and phase 2 as a codex phase, both with telemetry on the dashboard timeline.

---

## API exposure decision (round-1 review)

`allow_delegation` is **YAML/CLI-only for now** — it is NOT surfaced in the workflow-detail API/projection or the dashboard in this plan. Rationale: it is an execution/provisioning concern, and the immediate goal is a working delegation path. The `feat/dashboard-provider-selector` branch already surfaces `provider`/`agent_id` in the detail model; surfacing `allow_delegation` (a "delegation" badge/toggle) is a natural follow-up on that same pattern and is tracked separately, not built here. No `just codegen` is required for this plan.

## Cross-repo sequencing

1. Land Part A (agentic-primitives PR) first; it produces the image both delegation and the committed reproducibility depend on.
2. Bump the `lib/agentic-primitives` submodule pointer in syntropic137 only after the agentic-primitives PR merges (per feedback_local_build_before_base_bump + submodule discipline).
3. Land Part B (syntropic137 PR, stacked on `feat/codex-bridge`).
4. Both PRs get a codex cross-model review before merge (feedback_codex_review_prs).

---

## Self-Review

**Spec coverage:** Part A covers preconditions 1 (both CLIs) + 3 (delegation skill baked). Part B covers precondition 2 (both auths, opt-in) + 3-for-codex (AGENTS.md surface) + proof. The user's design (both auths opt-in, base skills baked into the image, prompt-driven "delegate here") maps to A2 (base skills), B1 (`allow_delegation` opt-in), B3 (both auths), B4 (codex surface), and B5's prompt-driven examples.

**Placeholder scan:** every code step shows real code; the only conditional ("create plugin.yaml if the bake needs it", A2 Step 2) is gated on an explicit verification with a fallback, not a TODO.

**Type consistency:** `allow_delegation: bool` is used identically across `AgentYamlDefinition`, `PhaseDefinition`, both `AgentConfiguration` classes, and `_auth_staging_for`. `_build_agent_config_from_phase` reads it via `getattr(..., False)` (matching the existing defensive pattern for provider/model). `_auth_staging_for` and `_delegation_note` signatures match their call sites and tests.

**Round-1 review resolution:** codex CHANGES REQUESTED (2026-07-23). All findings addressed above - the critical "plugins don't reach headless claude" is fixed by delivering delegation guidance via the injected CLAUDE.md/AGENTS.md content (Task B4, both directions) rather than `--plugin-dir`; the phase-update field-wipe is fixed (B2b); the shared-workspace assumption is replaced with artifact handoff (B5); the raw `docker build` is replaced with `scripts/build-provider.py` (A1/A2); `allow_delegation` is rejected for `claude-interactive` (B1 Step 3b); manifest version bump + image publish/verify added (A2); isolation wording corrected; API exposure recorded as YAML-only. The previously-open risk (delegation-plugin bakeability) is **resolved**: `plugins/delegation/.claude-plugin/plugin.json` exists, matching the other baked plugins, so `stage_plugins()` handles it with no extra metadata.

**Remaining verification-time unknowns (call out, do not silently assume):** the exact injected input-artifact path in B5 (confirm from `inject_from_previous_phases_explicit` at build time) and that `docker exec` claude actually auto-loads `/workspace/CLAUDE.md` in this runtime (verify in B6 by observing the delegated sub-run).
