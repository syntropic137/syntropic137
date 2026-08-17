# Skill Distribution: bundled and external skills through the marketplace

**Date:** 2026-08-17
**Status:** Approved design, not yet implemented
**Related:** ADR-066 (separation of concerns), #772 skills injection (plan 1 of 3), EXP-V1-0005 agent recipe standard (explicitly out of scope, see below)

## Purpose

Make workflow plugins able to carry the skills their phases need, so a user can
install a plugin and run it without registering skills out of band.

This is the last gap between "skills injection works" and "skills injection is
usable". The mechanism already works end to end and is verified: a codex phase
with `allow_delegation: true` had `delegating-to-claude-p` injected, and codex
stated *"I'm using the delegating-to-claude-p skill"* before shelling out to
Claude. What is missing is **distribution and ergonomics**, not capability.

The motivating use case is running Syntropic137 for real orchestrated
development and evals: a phase needs a specific skill set, reproducibly, without
a manual registration step before every workflow.

## Current state

Two layers exist today and already share one install seam
(`skills add --agent <key>`), differing only in source.

| Layer | Owner | Source | Installed |
|---|---|---|---|
| **1. Platform** | us, as we build Syntropic137 | baked into the workspace image at `/opt/agentic/plugins/*/skills` | conditionally (e.g. delegation-enabled phases) |
| **2. Workflow** | the workflow author | registered via API -> MinIO -> materialised to `/workspace/.syn-skills/<name>/` | per phase, from `skills:` |

Relevant facts:

- `skills:` is accepted at **both** workflow and phase scope; phase-scope merges
  with workflow-scope (phase wins on exact identity collision, else additive).
- Skill storage is **already content-addressed**: `skills/sha256-<hash>/`.
- The `skills` CLI baked into the image **is** the Vercel tool, pinned at 1.5.14.
  Agent keys: `claude-code`, `codex`, `gemini-cli`.
- `@latest` is rejected; refs must be pinned.
- The **only** write surface is `POST /skills/registrations`. There is no list,
  get, or delete, and no `syn skill*` CLI.
- `syn workflow install` runs a **claude-plugin** preflight but **no skills
  preflight**, so a workflow declaring `skills:` installs cleanly and then fails
  at execution with `SkillNotRegistered`.
- The marketplace serves workflows and claude plugins only; it does not serve
  skills. Its index already carries a type discriminator
  (`syntropic137.type: "workflow-marketplace"`), so it is extensible.

## Decision

### D1. Two skill sources, one store

A plugin declares skills either way, at workflow or phase scope:

```yaml
skills:
  - ./skills/repo-conventions                  # bundled: path inside the plugin
  - anthropics/skills/frontend-design@v1.2.0   # external: pinned ref
```

Both resolve into the same content-addressed store. Bundled skills are read from
the already-cloned plugin; external refs are shallow-cloned once.

Skills are just directories of `.md` files, so bundling costs the marketplace
nothing structurally - a plugin gains a `skills/` directory beside `workflows/`.

### D2. The content hash is the cache

Registration is keyed by `sha256` over the normalised file tree. A ref that
resolves to an already-registered hash performs **no network work**. First use of
a skill pays a shallow clone; every later install and every run reuses it.

This is why pinned refs matter: `@latest` cannot be cached honestly, because the
same ref may denote different bytes tomorrow. Its existing rejection is load
bearing for this design, not merely hygiene.

### D3. Registration moves to install time

`syn workflow install` gains a skills preflight, mirroring the claude-plugin one:

```
clone plugin
  -> parse workflow.yaml, collect skills: refs (workflow + phase scope)
  -> for each ref: already registered by hash? skip : fetch and register
  -> only then create the workflows
```

A bad or unreachable ref fails the **install**, not the run. Today the failure
lands at execution, after the user has committed to a workflow run - the
expensive place to discover a typo.

### D4. Per-phase injection is unchanged

Resolution, materialisation to `/workspace/.syn-skills/<name>/`, and
`skills add --agent <key>` all stay as they are. This design adds no new
injection path; it only ensures the skills are registered before a run needs them.

Existing behaviour to preserve:
- a phase declaring skills with no materialiser wired **fails** rather than
  running skill-less;
- conflicting versions of the same skill name abort the run.

### D5. Layer 1 stays baked into the image

Platform skills are the base level Syntropic137 needs to operate as expected.
We adjust them as we build the platform; users define their own in workflows.
That ownership split is the reason for the sourcing split.

Baking means they are pinned with the image, cannot be broken by a registry
outage, and version with the harness they steer. Both layers already share the
`skills add` seam, so nothing is duplicated - only the source differs.

**Corollary worth stating:** if a platform skill ever needs to change without an
image rebuild, that is a signal it is not platform-level and belongs in Layer 2
as an ordinary plugin skill.

### D6. Cache size is observable; eviction is not implemented

Content-addressed storage grows monotonically. This design does **not** add
eviction, and says so rather than implying it is handled.

It does add visibility: report total skill-store size and object count (a
`syn` command or an existing metrics surface, whichever fits). Skill trees are
small relative to session logs, so the expected outcome is "this is not the
thing to worry about" - but measured rather than assumed.

## Out of scope

Named explicitly, because each was considered and deferred:

| Item | Why deferred |
|---|---|
| **EXP-V1-0005 agent recipe standard** | 0 RunSpec files on main, 17/17 workflows non-conforming. A foundational refactor, not a feature. Should eventually conform, and this design is compatible with a later Recipe layer because it does not change the workflow schema's shape. Polish enhancement. |
| **MCP per-phase tools/skills** | A separate design. Distributing tools through MCP is a different delivery mechanism with its own trust boundary. |
| **`syn skill*` CLI and a read API** | Nothing in this design needs it; registration becomes implicit at install. Worth adding when a user needs to answer "what is registered?" |
| **Cache eviction** | See D6. |

## Consequences

**Positive**
- Install a plugin, run it. No out-of-band registration step.
- Bundled and external both supported, without forking skill hosting.
- Caching falls out of content-addressing that already exists.
- The agent container needs no egress for skills; the platform fetches, the
  workspace receives injected files.
- Failure moves from run time to install time.

**Negative / costs**
- The **platform** needs egress to fetch external skills. Same posture as the
  existing marketplace clone, but it means a skill cannot be hosted somewhere
  only the workspace can reach.
- Skill storage grows without bound until eviction exists (D6).
- Install becomes slower on first encounter with an unseen skill.

## Open question

**Version identity for bundled skills.** An external ref carries one
(`@v1.2.0`); `./skills/foo` does not. Options:

1. Hash the file tree (most honest: editing the skill produces a new
   registration, which is exactly true).
2. Tag with the plugin's own version (fewer registrations, but a skill can then
   change content without changing identity - the failure mode this whole design
   avoids elsewhere).

Recommend (1), consistent with D2. Flagged rather than silently chosen because
it affects how often bundled skills re-register during authoring.

## Verification

- Install a plugin with a bundled skill and a pinned external skill; assert both
  register and the workflow runs with both injected.
- Install the same plugin twice; assert the second install performs no fetch
  (hash hit) and completes measurably faster.
- Install a plugin whose `skills:` ref is unreachable or malformed; assert the
  **install** fails and no workflow is created.
- Run a phase declaring a skill and assert, inside the workspace, that
  `skills list` reports it installed for the correct agent key - not merely that
  files landed in `.syn-skills/`.
- Assert `@latest` is still rejected.
- Report skill-store size and object count.
