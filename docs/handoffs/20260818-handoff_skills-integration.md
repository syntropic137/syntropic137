# Handoff: Skills integration (#772) - shipped, with three deliberate deferrals

**Date:** 2026-08-18 (revised 2026-08-18, see Revision history)
**Repo:** git@github.com:syntropic137/syntropic137.git   **Branch:** main
**Status:** skills shipped to `origin/main`; release blocked on an unmerged local
divergence and two unproven integrations. See "Release readiness" below.

## Purpose & Vision

A workflow plugin should carry the skills its phases need so that installing it
and running it requires no out-of-band setup. This was the stated release
blocker: skills-per-phase is what makes codex phases useful, because Claude
plugins are Claude-only by construction.

Spec: [#772](https://github.com/syntropic137/syntropic137/issues/772) and
`docs/superpowers/specs/2026-08-17-skills-distribution-design.md`.

## Current State

**Shipped to `main` (2026-08-18), not yet promoted to `release`:**

- `6aca235c` (#824) skills register at install time
- `5052b983` (#829) `syn skill list | show | add`
- `150e3541` (#831) skills guide + ADR-065 rewrite
- `49a11ed1` (#819) image digest pinning (not ours, landed alongside)

**Verified end to end on a live stack**, not only in unit tests: a codex phase
declaring a bundled skill ran, and `skills list --agent codex` inside the
container reported it installed at `./.agents/skills/repo-conventions`. That is
the check that distinguishes "files staged under `.syn-skills/`" from "skill
installed for the agent" - staging alone passes a naive check.
Evidence: `docs/testing/output/skills-distribution-e2e.md` (gitignored).

**Open, deliberately deferred:**

- [#828](https://github.com/syntropic137/syntropic137/issues/828) remove
  `claude_plugins:` - unused, and NOT urgent; see Rationale
- [#775](https://github.com/syntropic137/syntropic137/issues/775) followup-phase
  injection - unreachable code path, gated behind interactive-tmux which is dropped
- [#784](https://github.com/syntropic137/syntropic137/issues/784) base-skill tier
- [#822](https://github.com/syntropic137/syntropic137/issues/822) `syn workflow
  install` is not idempotent - pre-existing, reproduced on released code
- [#821](https://github.com/syntropic137/syntropic137/issues/821) projection event
  map gaps

## Release readiness (added 2026-08-18)

This handoff originally covered only #772. Two further arcs are now in play and
must land before a release is cut. Neither was mentioned in the original text.

### The local checkout has diverged from `origin/main` and is not pushed

`main` in the primary checkout is **6 commits ahead and 4 behind**
`origin/main`. The omni-agent integration exists ONLY in those unpushed local
commits. It is not on `origin/main`, so nothing built from the remote has it.

Local-only (unpushed): `f6e733b6`, `16535fa2`, `68e6beb0`, `8c30450d`,
`06e284aa`, `d04e664a`.
On `origin/main` but not local: `6aca235c`, `49a11ed1`, `5052b983`, `150e3541`,
`9debfd1e`, `4c7459e1`.

**Merging these conflicts in three places, and one of them is a runtime crash,
not a textual conflict:**

1. `packages/syn-shared/src/syn_shared/settings/workspace_images.py` was
   rewritten on both sides. `origin/main` (#819) replaced the mutable
   `DEFAULT_TAG` with `PINNED_DIGESTS` and returns `repository@digest`. The
   local omni commits were built on the old tag-based version.
2. `PINNED_DIGESTS[provider]` is a **direct subscript**. `WorkspaceImageProvider`
   gains `OMNI_AGENT` from the local side with no digest entry, so selecting
   omni raises `KeyError` at workspace provision time. The module docstring
   already states the rule: a new provider needs a matching `PINNED_DIGESTS`
   entry.
3. `origin/main` hardcodes `f"{IMAGE_PREFIX}-{provider.value}"` inside
   `workspace_image_ref`, so the `IMAGE_NAME_OVERRIDES` / `workspace_image_name()`
   fix from `d04e664a` is absent there and must be re-applied. Without it omni
   resolves to `agentic-workspace-omni-agent`, which does not exist. It publishes
   as `omni-agent-workspace`.

Submodule pointer also conflicts: local pins agentic-primitives `46c915e0`,
`origin/main` pins `ee2c248`. **Take `ee2c248`** - it is a descendant of
`46c915e0` and carries the `< /dev/null` codex exec stdin fix (AP #338) plus
delegation 1.2.2.

### Omni-agent image

Registered locally in `06e284aa` / `d04e664a`. `ghcr.io/agentparadise/omni-agent-workspace:latest`
**is now published** (verified 2026-08-18 via `docker manifest inspect`), which
retires the "not yet published" caveat written into `06e284aa`.

Still open: the default remains `CLAUDE_CLI`. Outside `workspace_images.py`
itself there is not one reference to `OMNI_AGENT` in `packages/` or `apps/`, so
nothing selects it. `SYN_WORKSPACE_DOCKER_IMAGE` is the existing override knob
for testing it without a code change.

### Central session storage

A separate arc, already merged on both sides, and currently switched off
everywhere:

- agentic-primitives PR #303 (MERGED): the `session-store` capability plus the
  seshmagic adapter, at `workspace/capabilities/session-store/` and
  `lib/python/agentic_session_store`. `providers/workspaces/claude-cli/Dockerfile`
  copies `workspace/capabilities/` into `/opt/agentic/capabilities/`, so
  claude-cli carries it too, not only omni.
- syn137 #815 (`f6b5bee1`, MERGED): `SessionStoreSettings` (`SYN_SESSION_STORE_*`)
  translated into the six `AGENTIC_SESSION_STORE_*` names in `env_constants.py`
  and injected into the workspace container. Opt-in, default off.

**Configuration is by 1Password vault field, and needs no code change.** The API
image bakes the `op` CLI (`infra/docker/images/syn-api/Dockerfile`) and
`settings/config.py` calls `resolve_op_secrets()` before `Settings()` is built.
`op_client.inject_fields()` injects every field on the `syntropic137-config`
item **keyed by its label**, with no allowlist, so two new fields per vault are
enough:

| Field label | Value |
|---|---|
| `SYN_SESSION_STORE_URL` | base URL of the central SeshMagic store |
| `SYN_SESSION_STORE_AUTH_TOKEN` | write token |

`SYN_SESSION_STORE_PROVIDER` and `SYN_SESSION_STORE_SPOOL_DIR` already default
to `seshmagic` and `/spool`. Vault names come from `APP_ENVIRONMENT` via
`op_resolver.py`: development to `syn137-dev`, beta to `syn137-beta`, selfhost
to `syntropic137`.

The empty `SYN_SESSION_STORE_URL=` in `.env` does NOT block this: `inject_fields`
skips only a truthy existing value, and an empty string is falsy.

Two gaps remain in that path:

- `docker/docker-compose.selfhost.yaml` enumerates env vars explicitly and passes
  the generic `OP_SERVICE_ACCOUNT_TOKEN`, not the per-vault
  `OP_SERVICE_ACCOUNT_TOKEN_SYN137_BETA` that `op_resolver.py` looks for. Beta
  cannot read its vault. Dev is fine only because
  `docker-compose.dev.yaml` loads the whole `.env` through `env_file`.
- `scripts/op_env_export.py` resolves a hardcoded 10-label allowlist that omits
  the session-store keys, so `just _env-check` reports them missing even when
  the vault holds them. Cosmetic, but a costly false negative.

### Never proven together

No run has exercised omni plus per-phase skill injection plus session capture at
once. AP #303's own verification was Claude only, one session, against the
EXP-07 test rig rather than a live store, with an exporter binary that is not
what any deploy ships. **Codex has never been run against the session store at
all.** The capability is also headless only.

**Next actions:** see `docs/plans/20260818_release-readiness.md`.

## Revision history

- **2026-08-18 (initial):** #772 skills integration as shipped.
- **2026-08-18 (revised):** added the Release readiness section. The original
  "Next actions" line said to promote `main` to `release` and optionally bump
  the submodule pin. That understated the work: the omni integration is
  unpushed and collides with #819's digest pinning, and session storage is
  merged but switched off. Corrected rather than superseded, per the
  one-current-document-per-topic convention.

## Files Affected

See `git diff 529a1ca2..150e3541`. The load-bearing ones:

- `apps/syn-cli-node/src/packages/skill-ref.ts` - ref parsing and `hashSkillTree`
- `apps/syn-cli-node/src/packages/skill-preflight.ts` - collect, register, and
  rewrite bundled refs before upload
- `apps/syn-cli-node/src/packages/skill-tree.ts` - tree reading, size bounds,
  `skillDirInClone`
- `apps/syn-cli-node/src/commands/workflow/install.ts` - now uploads the resolved
  definition to `/workflows/from-yaml`
- `apps/syn-cli-node/src/commands/skill/` - the `syn skill` command group
- `apps/syn-api/src/syn_api/routes/skills.py` - read endpoints
- `packages/syn-domain/.../register_skill/RegisterSkillHandler.py` - hash-version
  enforcement
- `packages/syn-adapters/.../object_storage/minio_queries.py` - recursive listing
- `docs/adrs/ADR-065-claude-plugin-injection.md` - rewritten in place

## Rationale & Key Decisions

**Bundled skills are pinned by their file-tree sha256, not a literal.**
`RegisterSkillHandler.handle` returns an existing aggregate *before* hashing the
submitted files. Under a fixed version like `"bundled"`, editing a skill would
silently resolve to the previously stored tree. With the hash in the version, an
edit is a different registration, which is what it is. A `sha256-<hash>` version
is now a content commitment the handler enforces.

**Install uploads the resolved definition to `/workflows/from-yaml`.**
It previously hand-built a narrow JSON body for `POST /workflows` that named each
field, silently dropping `skills:` and `claude_plugins:` entirely - so
registration alone would have done nothing. The narrow body was the bug; it was
deliberately NOT widened, because widening fixes `skills` and leaves the same
hole for the next field. `application/json` is accepted there because JSON is a
YAML subset and the CLI has no YAML emitter.

**The CLI rewrites bundled refs into pinned ones before upload.** The Python
domain never accepted `./skills/foo` (verified by running it), and rather than
teach it a path form, resolution happens where `prompt_file:` resolution already
happens. The API only ever sees pinned refs.

**Two capability layers, split by ownership.** Hooks live in the workspace image
at `/opt/agentic/plugins/`; skills are workflow-declared. This is why #828 is not
urgent: removing `claude_plugins:` does NOT touch hooks. That confusion cost real
time and is now documented in `guide/skills.mdx`.

**ADR-065 was rewritten in place, not superseded.** Maintainer preference: one
current ADR per topic. A Revision history section preserves why each change
happened.

## Do's and Don'ts (learned this session)

- **Do** add `< /dev/null` to every `codex exec` invocation. The
  `delegation:delegating-to-codex` skill's canonical form omits it, and following
  it verbatim hangs forever on "Reading additional input from stdin". Detection:
  the `--json` stream file stalls at 39 bytes. This burned ~45 minutes across two
  runs before it was spotted. See `patterns_codex_exec_stdin_hang` memory.
- **Do** merge with merge commits. **Don't** squash. Squashing #824 rewrote its
  commits and instantly put stacked #829 into `CONFLICTING` across nine files.
- **Do** run the codex review round. Both PRs that got one returned DO NOT SHIP
  and both found real bugs: a content-substitution hole and a filesystem escape
  in #824, and an identity mismatch in #829 that made `syn skill add` register
  something no workflow could resolve.
- **Don't** write tests that construct a response model and assert its own
  fields. Three such tests in this work passed against completely broken code. A
  route test must call the route; a routing test must go through FastAPI, not the
  handler function.
- **Do** check `pytest` markers on new API tests. CI runs only `-m unit` and
  `-m integration`; unmarked tests are collected locally and never run in CI.
  46 tests were silently not running.
- **Don't** trust a stub that is more convenient than the real thing. The MinIO
  stats stub returned flat keys; real MinIO returns directory prefixes, so
  `total_bytes` was 0 in production and the stubbed test passed anyway.
- **Do** re-check submodule state before reporting it. A "3 commits behind"
  claim about agentic-primitives was stale by the time it was said.

## Important Context to Keep in Mind

- **`syn workflow install` is not idempotent** (#822). Re-installing a package
  whose workflow id exists fails with a raw event-store concurrency error. Not
  caused by this work - reproduced with the released CLI against a released
  stack. The skills preflight correctly reports "already registered" first.
- **The e2e requires an isolated env**, not the shared stacks. `just env-up
  current` allocates a slot; `just env-down <name>` frees it. The worktree needs
  its own `.env` (copy from the main checkout) and `git submodule update --init`.
- **Direct API port serves at root; the gateway carries `/api/v1`.** Pointing the
  CLI at the direct port yields confusing 404s on every route.
- **`docs-sync` fails in a fresh worktree** because `.topology/` is gitignored.
  Run `vsa manifest --config vsa.yaml --output .topology/syn-manifest.json
  --include-domain` first. Note that the committed architecture docs are already
  stale relative to the current generator, independent of any change.
- **The TS and Python tree hashes must agree byte for byte.** Both sides assert
  the same constant; JS sorts by UTF-16 code unit and Python by code point, which
  diverge for non-BMP filenames, so ordering is specified as UTF-8 bytes.

## Suggested Skills

- `superpowers:test-driven-development` - the failing-test-first loop is what
  surfaced the event-map and MinIO recursion bugs
- `delegation:delegating-to-codex` - for the review round, but add `< /dev/null`
- `sdlc:git-worktree` - parallel branch work; this repo has multiple live sessions
- `syntropic137:platform-ops` - stack lifecycle and troubleshooting

## References

- Spec: `docs/superpowers/specs/2026-08-17-skills-distribution-design.md`
- Plan: `docs/superpowers/plans/2026-08-17-skills-distribution.md` (includes a
  "What changed during implementation" section recording where it was wrong)
- ADR: `docs/adrs/ADR-065-claude-plugin-injection.md`
- Guide: `apps/syn-docs/content/docs/guide/skills.mdx`
- Runbook: `docs/testing/post-release-validation.md` section 6.2
- PRs: #824, #829, #831
