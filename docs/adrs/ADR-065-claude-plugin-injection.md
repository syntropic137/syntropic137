# ADR-065: Skills as the Workflow Capability Unit

- **Status**: Accepted (revised 2026-08-17; see "Revision history" at the end)
- **Date**: 2026-05-04, last revised 2026-08-17
- **Issue**: [#772](https://github.com/syntropic137/syntropic137/issues/772) (current), [#726](https://github.com/syntropic137/syntropic137/issues/726) (original claude-plugin design)
- **Related**: ADR-020 (Bounded Context Convention), ADR-024 (Workspace Setup Phase), ADR-033 (agentic-primitives `--plugin-dir` injection), [ADR-066](ADR-066-separation-of-concerns.md) (Separation of Concerns)

## Context

Agents inside a Syntropic137 workspace need capabilities beyond the base image: repository conventions, review rubrics, workflow-specific instructions. The platform needs a primitive for declaring "this workflow needs these capabilities" in YAML, resolving the references reproducibly, and getting them into each workspace at setup time.

The original design used **Claude Code plugins** as that unit, injected via `claude --plugin-dir`. That worked, but it is Claude-only by construction: `--plugin-dir` is a Claude CLI flag, the manifest requirement is `.claude-plugin/plugin.json`, and Codex or Gemini phases received nothing. Multi-harness execution made that a dead end.

**Skills** are the replacement: a folder containing `SKILL.md` with YAML frontmatter, per the [vercel-labs/skills](https://github.com/vercel-labs/skills) convention. They are simpler than plugins, natively discovered by both Claude Code and Codex, and backed by a maintained ecosystem that tracks where 70+ harnesses look for them.

## Decision

### 1. Two capability layers, split by ownership

| | Platform layer | Workflow layer |
|---|---|---|
| Unit | Claude plugins (hooks, commands, guardrails) | Skills |
| Source | Baked into the workspace image at `/opt/agentic/plugins/` | Declared in workflow YAML |
| Owner | The platform, as we build it | The workflow author |
| Changes with | An image rebuild | A workflow edit |
| Harness | Claude-specific (`--plugin-dir`, ADR-033) | Harness-agnostic |

The split is by ownership, not by technology. A hook fires on an event; a skill is instructions an agent reads. Observability capture and dangerous-command protection are hooks, so they belong with the harness they steer and version with the image. They are deliberately not workflow-declarable.

**Corollary:** if a platform capability ever needs to change without an image rebuild, that is evidence it is not platform-level and belongs in the workflow layer as an ordinary skill.

### 2. Terminology

`skills:` in YAML, `Skill*` in code. Never bare `plugin`, which collides with Syntropic's marketplace "workflow plugin" concept. The older workflow-scoped `claude_plugins:` field still exists and is unused; its removal is [#828](https://github.com/syntropic137/syntropic137/issues/828).

### 3. Bounded context placement

`SkillRegistration` lives in the existing `orchestration` bounded context. Per ADR-020, multiple aggregates belong in one context when they share domain language: skills are workspace inputs, the same family as `Workspace`, `Workflow`, and `WorkflowExecution`. No new top-level context.

### 4. Scopes

`skills:` is accepted at workflow scope and phase scope. Phase scope merges with workflow scope, phase winning on exact identity collision, otherwise additive. Conflicting versions of the same skill name abort the run rather than picking one silently.

Skills have no global scope. Anything that should apply everywhere is platform-level and belongs in the image.

### 5. Reference forms

Three, all normalized to one identity:

- `org/repo/skill-name@version` - the third segment names the skill folder, because a skills repo commonly publishes several
- `<url>@<version>` - full URL, name defaults to the URL basename minus `.git`
- verbose mapping with `source`, `version`, and either `name` or `names: [a, b]`
- `./path/inside/plugin` - bundled: a skill shipped inside the workflow plugin itself

### 6. Identity, lock, and storage

| Concern | Choice |
|---|---|
| Lock key | `(source_url, version, skill_name)` -> `resolved_sha + tree_storage_prefix` |
| Aggregate stream id | `skill-{sha256(source_url\|version\|skill_name)}` (deterministic) |
| Storage | MinIO, content-addressed at `skills/sha256-<hash>/...` |
| Tree hash | sha256 over sorted `(rel_path, content)` pairs, each NUL-terminated, ordered by UTF-8 bytes |
| First-writer-wins | `ExpectedVersion.NoStream` on first event |

`skill_name` is in the key because a marketplace repo publishes multiple skills at one `(source_url, version)`; keying on the pair alone would collapse them and let the first registration shadow the rest.

The tree hash ordering is specified as UTF-8 bytes rather than "sorted" because the CLI and the API implement it in different languages. JavaScript orders strings by UTF-16 code unit and Python by code point; those disagree for non-BMP filenames, which would produce a different digest per language and silently break both the cache and resolution.

### 7. `@latest` is rejected, and this is load-bearing

Registration is content-addressed and the hash **is** the cache: a reference resolving to an already-stored hash performs no network work. An unpinned reference cannot be cached honestly, because the same reference may denote different bytes tomorrow.

So pinning is a correctness requirement of the caching design, not a reproducibility nicety. Any change that relaxes it invalidates the cache.

### 8. Bundled skills are pinned by their tree hash

An external reference carries a version; a path inside a plugin does not. The CLI computes the sha256 of the file tree and rewrites the reference into a pinned one before upload, so the API only ever sees pinned references and the Python domain needs no relative-path form.

The alternative, a fixed literal such as `"bundled"`, was rejected: `RegisterSkillHandler` returns an existing aggregate *before* hashing submitted files, so an edited skill under a fixed version would silently resolve to the previously stored tree. With the hash in the version, an edit is simply a different registration, which is what it is.

A `sha256-<hash>` version is therefore a content commitment, and the handler enforces it: a submitted tree whose hash disagrees is rejected rather than stored.

### 9. Resolution tier

Git work happens in the CLI, never the API (ADR-066). The CLI clones, walks the tree, and uploads base64 contents to `POST /skills/registrations`; the API validates the manifest, computes the sha, stores, and dispatches the command. No subprocess spawn and no `git` binary in the API image.

### 10. Registration happens at install time

`syn workflow install` collects every declared reference and registers what is missing **before creating any workflow**. A bad or unreachable reference fails the install, not the run.

The alternative was failing at execution, which is the expensive place to discover a typo: the user has already committed to a run.

### 11. Injection is the vercel `skills` CLI, not ours

Resolved trees are materialized to `/workspace/.syn-skills/<skill-name>/`, then the pinned `skills` CLI installs each one for the phase's harness from that local path, offline.

We do not own the harness mapping. Three harnesses today, but the mapping table is the genuinely hard-to-maintain part, and upstream maintains it for 70+ harnesses. Local-path installs keep provisioning deterministic and network-free.

**Staging is not installation.** Files under `.syn-skills/` are the drop point; `skills add` performs the per-harness install. Verification must assert the latter, inside the container.

### 12. Fail loudly, never skill-less

A phase that declares skills and cannot install them fails. Running an agent without capabilities it was told to have produces a plausible-looking result against the wrong setup, which is worse than a clear failure.

## Consequences

### Positive

- One declaration works across Claude and Codex; the harness mapping is upstream's problem.
- Caching falls out of content-addressing that already existed.
- Failure moves from run time to install time.
- The agent container needs no egress for skills: the platform fetches, the workspace receives files.
- Bundled skills make a workflow plugin self-contained; installing it needs no out-of-band registration.

### Negative

- The **platform** needs egress to fetch external skills, so a skill cannot be hosted somewhere only the workspace can reach.
- Skill storage grows without bound until eviction exists. Deliberately not implemented; size is reported instead (`GET /skills/storage`).
- First use of an unseen skill pays a shallow clone.
- Skills cannot express hooks or commands. That capability lives only in the platform layer, so a workflow cannot ship a hook.
- Editing a bundled skill during authoring produces a new registration each time. Honest, but chatty.

## Alternatives considered

- **Keep Claude plugins as the workflow unit.** Rejected: Claude-only by construction, which blocks multi-harness execution. Plugins remain the *platform* unit, where their Claude specificity is fine.
- **Own the harness mapping ourselves.** Rejected: it is the part that rots. Upstream maintains it for 70+ harnesses and we pin the version.
- **Tag bundled skills with the plugin's own version.** Rejected: fewer registrations, but a skill could then change content without changing identity, which is the exact failure mode this design avoids elsewhere.
- **A separate `skills` bounded context.** Rejected as premature. Single aggregate family sharing orchestration's domain language.
- **Cache eviction in v1.** Deferred. Skill trees are small relative to session logs, and the expected answer is "this is not the thing to worry about" - but measured rather than assumed.
- **Per-skill granularity out of a plugin.** This is what skills are; the plugin-era limitation is gone.

## Validation

- `skills list --agent codex` inside a running workspace reports the declared skill installed at `./.agents/skills/<name>`, not merely staged under `.syn-skills/`. This is the check that distinguishes the two.
- Second install of the same package reports `already registered` and performs no upload, which is the caching claim.
- An unreachable reference fails the install and creates no workflow.
- The stored `WorkflowTemplateCreated` payload and the `skill_lock` key carry byte-identical identity triples, so install-time and run-time identity agree.
- CLI and API tree-hash implementations assert the same constant from both languages.

## References

- [#772](https://github.com/syntropic137/syntropic137/issues/772) -- harness-agnostic skill injection
- [#726](https://github.com/syntropic137/syntropic137/issues/726) -- the original claude-plugin design this replaces
- [#828](https://github.com/syntropic137/syntropic137/issues/828) -- removal of the unused `claude_plugins:` field
- ADR-020 -- Bounded Context and Aggregate Convention
- ADR-024 -- Workspace setup phase and secret injection
- ADR-033 (agentic-primitives) -- `--plugin-dir` injection, still how the platform layer loads
- ADR-066 -- Separation of Concerns; why git work lives in the CLI
- `docs/superpowers/specs/2026-08-17-skills-distribution-design.md` -- the distribution design

## Revision history

**2026-08-17 -- skills replace claude plugins as the workflow capability unit.**
The original ADR made Claude plugins the workflow-declared unit, injected with `--plugin-dir`. That is Claude-only, so Codex and Gemini phases got no capability injection at all, which blocked multi-harness execution. Skills replace it at the workflow layer; Claude plugins remain the platform layer, where their Claude specificity is appropriate and where the hooks live. Also added in this revision: bundled references and their tree-hash pinning, the byte-order specification for cross-language hashing, install-time registration, and the fail-loudly rule.

**2026-05-05 -- resolution moved from the API to the CLI.**
The original design had the API container perform the git clone, hash, and upload during workflow registration. That leaked heavy I/O into the API tier and was caught during the first end-to-end smoke against the dev stack: the `git` binary was missing from the API image, and adding it would have masked the underlying violation. [ADR-066](ADR-066-separation-of-concerns.md) is the corrective principle. The lock projection and everything below the resolution tier were unchanged. See `docs/experiments/cycle-004/dogfood-platform-726/redesign-thin-api.md` and `retro-git-in-api.md`.

**2026-05-04 -- original decision.** Workflow-scoped Claude plugin injection, validated end-to-end before platform code was written (`docs/experiments/cycle-004/dogfood-platform-726/validation-experiment/run.sh`, 10/10 tests passing, including a 20-skill real-world plugin loading with correct namespacing).
