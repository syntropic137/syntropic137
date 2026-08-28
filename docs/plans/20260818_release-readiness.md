# Release readiness plan: skills + omni + central session storage

**Date:** 2026-08-18
**Repo:** `/Users/neural/Code/Syntropic137/syntropic137`   **Branch:** `main`
**Goal:** get `main` into a state worth running pre-release validation against,
then cut a release.

Context and evidence for every claim below:
`/Users/neural/Code/Syntropic137/syntropic137/docs/handoffs/20260818-handoff_skills-integration.md`.

## The shape of it

Three arcs converge. Two are code-complete, one is configuration-only:

| Arc | Code | Wired on | Proven live |
| --- | --- | --- | --- |
| Skills per phase (#772) | done | `origin/main` | yes, codex phase, in-container |
| Omni-agent image | done | **local only, unpushed** | image verified, never selected |
| Central session storage (#815 + AP #303) | done | both, but switched off | no |

Nothing here needs a feature built. The work is reconciliation, configuration,
and one honest end-to-end run.

## Phase 0: stop the bleeding (blocking, do first)

The primary checkout is 6 ahead / 4 behind `origin/main` and the omni work is
in the unpushed half. Every hour that gap stays open makes the reconciliation
worse, and it is already a runtime crash rather than a textual conflict.

**0.1 Reconcile `workspace_images.py`.** Merge `origin/main` into `main` in a
worktree, not the primary checkout. Resolve by taking `origin/main`'s
digest-pinned structure as the base and re-applying the omni work on top:

- keep `PINNED_DIGESTS` and the `repository@digest` return form from #819
- re-apply `IMAGE_NAME_OVERRIDES` and `workspace_image_name()` from `d04e664a`,
  and route `workspace_image_ref` through it. `origin/main` hardcodes
  `f"{IMAGE_PREFIX}-{provider.value}"` inline, so the override is lost on a
  naive merge and omni resolves to a repository that does not exist.
- **add an `OMNI_AGENT` entry to `PINNED_DIGESTS`.** `PINNED_DIGESTS[provider]`
  is a direct subscript. Without the entry, selecting omni is a `KeyError` at
  provision time. Resolve the digest from
  `ghcr.io/agentparadise/omni-agent-workspace:latest` and record the resolution
  date in the comment block, matching the existing convention.

**0.2 Take `ee2c248` for the agentic-primitives submodule.** It is a descendant
of the local `46c915e0` and carries the `< /dev/null` codex exec stdin fix
(AP #338) plus delegation 1.2.2. That fix matters directly: the same hang cost
about 45 minutes during the #772 work.

**0.3 Verify the merge with a mutation check, not a green suite.** Temporarily
remove the `OMNI_AGENT` digest entry and confirm something fails. `d04e664a`
already established this bar for the name override (removing it failed three
tests); the digest pin deserves the same. A cross-repo contract test that reads
the submodule manifests already exists. Extend it to assert every enum member
has a digest.

**0.4 Push.** Until this lands on `origin/main`, no CI, no image build, and no
validation run reflects reality.

## Phase 1: turn session storage on

Configuration only. No code change is needed for the API to pick these up:
the API image bakes the `op` CLI, `config.py` resolves 1Password before
`Settings()` is constructed, and `inject_fields()` injects every field on the
`syntropic137-config` item by label with no allowlist.

**1.1 Add two fields per vault.** Item `syntropic137-config`, field labels
exactly:

| Field label | Value |
| --- | --- |
| `SYN_SESSION_STORE_URL` | base URL of the central SeshMagic store |
| `SYN_SESSION_STORE_AUTH_TOKEN` | write token |

Vaults: `syn137-dev` (`APP_ENVIRONMENT=development`) and `syn137-beta`
(`APP_ENVIRONMENT=beta`). Skip `SYN_SESSION_STORE_PROVIDER` and
`SYN_SESSION_STORE_SPOOL_DIR`; they already default to `seshmagic` and `/spool`.

**1.2 Fix the beta passthrough.** `docker/docker-compose.selfhost.yaml`
enumerates env vars explicitly and passes the generic
`OP_SERVICE_ACCOUNT_TOKEN`, not the per-vault
`OP_SERVICE_ACCOUNT_TOKEN_SYN137_BETA` that `op_resolver.py` derives and looks
for. Beta cannot read its vault today.

Recommended fix: give the selfhost overlay the same `env_file` treatment the dev
overlay has, so the next vault field needs no compose change either. The
enumerate-every-variable approach is what created this gap and will recreate it.
If a narrower change is preferred, add the per-vault token names explicitly and
accept that the next one will be missed.

**1.3 Close the `_env-check` false negative.** `scripts/op_env_export.py`
resolves a hardcoded 10-label allowlist (`_KEYS`) that omits the session-store
keys, so `just _env-check` reports them missing even when the vault holds them.
Cosmetic, but exactly the false negative that burns an hour mid-validation. Add
the two labels, or better, stop maintaining a parallel allowlist and export what
the item actually contains.

**1.4 Confirm the empty-`.env` interaction holds.** `.env` ships
`SYN_SESSION_STORE_URL=` (empty). `inject_fields` skips only a truthy existing
value, so the vault value should win. This is reasoned, not observed. Assert it
with a test rather than discovering it on the stack.

## Phase 2: the run that actually proves it

One workflow run exercises all three arcs at once. Do it on the dev stack before
touching any default.

**2.1 Point dev at omni without a code change.** Set
`SYN_WORKSPACE_DOCKER_IMAGE` to the pinned omni digest reference. The knob
already exists (`WorkspaceSettings.docker_image`, prefix `SYN_WORKSPACE_`).

**2.2 Run a workflow with a codex phase declaring a bundled skill.** The
acceptance check is the one #772 established, and it is stricter than it looks:
`skills list --agent codex` **inside the container** must report the skill
installed. Files staged under `.syn-skills/` pass a naive check and prove
nothing.

**2.3 Confirm capture in the store, not in the spool.** Query the central store
for the session and check it carries a real container hostname as `origin_host`
and the partition tags. AP #303's finalize path reports
`discovered/uploaded/accepted/failed`; a clean sweep is the signal.

**2.4 Run it twice.** The second sweep must report `skipped_unchanged` and the
store must hold one row, not two. That is the only thing that exercises the
exporter state file, and AP #303 notes it had never been exercised before their
final run.

**Expect this phase to find something.** Codex has never been run against the
session store at all: AP #303's verification was Claude only, one session, one
partition, against the EXP-07 test rig rather than a live store, with an exporter
binary that is not what any deploy ships. The rig authenticates reads while
production serves them open (seshmagic#35), so the unauthenticated-read path is
untested. Budget for a fix round here rather than treating it as a formality.

**2.5 Flip the default to omni only after 2.2 through 2.4 pass.**

## Phase 3: triage the open issues before cutting

These are open and unassessed against a release bar. Decide ship-or-defer
explicitly rather than by omission:

- **#803 phase tool allowlists are silently discarded**, so every shipped
  workflow that restricts tools runs unrestricted. This is a security
  regression in a user-facing promise. Assess first; it is the most likely
  genuine blocker on the list.
- **#825 45% of the Python suite runs in no CI job**, two tests were failing on
  `main` unnoticed. A green CI run currently asserts less than it appears to,
  which weakens every other gate in this plan.
- **#822 `syn workflow install` is not idempotent.** Pre-existing, reproduces on
  released code. Reinstalling a package whose workflow id exists fails with a
  raw event-store concurrency error. Users will hit this immediately.
- **#821 projection event map gaps**, **#828** remove `claude_plugins:`,
  **#784** base-skill tier, **#775** followup-phase injection (unreachable,
  gated behind the removed interactive-tmux path).

## Phase 4: pre-release validation

Use the **pre-release** mode in
`/Users/neural/Code/Syntropic137/syntropic137/docs/testing/release-validation.md`:
on-demand env (ADR-060), port `<slot>8137`, images built from the working tree.
Do not validate on the dev stack; dev images are locally built and may carry
uncommitted changes, so results there do not validate release quality.

Note from prior experience: the selfhost overlay cannot run beside a live stack,
and `npx setup update` only pulls the last release, so neither is a substitute
for the on-demand env here.

## Sequencing and what blocks what

```
Phase 0 (merge + digest pin + push)   <- blocks everything
        |
        +--> Phase 1 (vault fields, beta passthrough)
        |            |
        +------------+--> Phase 2 (one run: omni + skills + capture)
                             |
Phase 3 (issue triage) ------+--> Phase 4 (pre-release validation) --> cut
```

Phase 3 can run in parallel with 1 and 2. Phase 0 blocks everything, including
any validation run, because the omni integration is not on the remote yet.

## Open question

The central store endpoint and write token are not in this repo and I have not
seen them. Phase 1 cannot start without them, and Phase 2 depends on Phase 1.
