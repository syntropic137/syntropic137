# Plan: make session capture work in Syntropic137 workspaces

**Date:** 2026-08-19
**Status:** draft, pending codex review
**Goal:** a Syntropic137 workflow phase produces an agent session that lands in
the central store, attributable to its deployment tier, with no vendor coupling
in the workspace image.

## The architecture this implements

```
APS-V1-0004  (public standard: envelope + three conformance profiles)
   |
   |-- reference exporter  --> PUBLIC, AgentParadise org
   |        implements the Exporter profile; depends ONLY on the standard crate
   |        |
   |        \--> baked into agentic-primitives workspace images
   |
   \-- SeshMagic  --> implements the RECEIVE side; stays private and paid
```

Nothing depends on SeshMagic. SeshMagic depends on the standard. agentic-primitives
depends on a vendor-neutral binary that implements a public contract.

This is the ordinary observability split (Sentry SDKs / sentry.io; Datadog agent /
Datadog backend). The client is public because users run it on their own machines
and will want to read it. The store is the product.

## Why it does not work today

Seven independent defects. Each one alone is sufficient to prevent a single
session reaching the store. Verified against running code, not inferred.

| # | Defect | Repo | Size |
|---|---|---|---|
| G1 | `--read-only` rootfs makes `/spool` unwritable; capability hard-fails the workspace at preflight | AP | small |
| G2 | Same `--read-only` breaks the doctor's audit redirect; entrypoint reports `doctor: FAIL` for a doctor that never ran, for EVERY capability | AP | small |
| G3 | Doctor probes the exporter with `--version`, which it does not implement; it ignores unknown flags and runs a full capture sweep, so preflight "passes" by performing a real upload | AP or exporter | small |
| G4 | No exporter binary in the image, and no mechanism to deliver one | AP + new repo | design |
| G5 | Store host does not resolve inside the container | syn137 config | one-line |
| G6 | Enabling with a URL but no token silently loses every session (`is_enabled` gates on URL alone; `/healthz` is unauthenticated but writes 401) | syn137 | small |
| G8 | No deployment identity reaches the store; every session lands as `"laptop"` with an ephemeral container ID as host | AP + syn137 | small |

(G7, spool durability, and G9, credential exposure, are deliberately out of scope
for first light. See "Explicitly deferred".)

## Phase 1: the standard defines the contract (APSS)

**Rationale:** without this, "the exporter implements the standard" is a claim
nobody can check, and G3 is the proof. The doctor invented a `--version` probe,
the exporter never implemented it, and no shared artifact could disagree. A CLI
substandard is what turns that into a build failure.

**1.1 Author `APS-V1-0004/substandards/EX01-exporter-cli`.** Follow
`APS-V1-0000-meta/substandards/SS01-substandard-structure`; model the content on
`CL01-cli-contract`, which is the existing precedent for specifying a CLI as a
substandard. Normative content:

- **Required flags and their semantics.** At minimum `--version` (side-effect
  free, the liveness probe), `--dry-run` (network-free, state-free), `--health`.
  Unknown flags MUST be rejected with a non-zero exit, never ignored. G3 exists
  because they are silently ignored.
- **Exit codes as an API.** Distinguish "nothing to upload", "uploaded", "partial
  failure", "configuration error", "store unreachable". A consumer that can only
  see zero/non-zero cannot tell a clean sweep from a rejected one.
- **Environment contract.** The `SESSION_STORE_*` variables, including
  `SESSION_STORE_ORIGIN_DEPLOYMENT` carrying `origin.deployment`.
- **Credential delivery.** The token MUST be readable from a file (mode 0600)
  and MUST NOT require being a process env var. This is what later closes G9
  without another contract change.
- **Sweep semantics and the state file.** What `skipped_unchanged` means, and
  that a state file round-trip is required rather than optional.
- **Conformance requirements for a shipped binary:** linux/amd64 and linux/arm64,
  and a signature. Consumers pin images by digest and cosign-verify; a
  single-arch unsigned binary cannot be embedded.

**1.2 Amend section 11 atomically with the move (Phase 2), not before.** The
current text says the reference implementation lives in the SeshMagic repository.
That is accurate until the move lands. The replacement text is already recorded
on PR #133.

**Exit criteria:** substandard exists with conformance tests; `cargo test` green;
#133 merged.

## Phase 2: extract and publish the exporter (SeshMagic -> AgentParadise)

**This is cheaper than it looks.** Verified: `crates/seshmagic-session-store-exporter`
depends on `apss-v1-0004-session-capture` plus third-party crates and **nothing
else in the SeshMagic workspace**. No dependency on the envelope crate, the
server crate, or any private type. Extraction is a move, not a refactor.

**2.1 Move the crate to its OWN public AgentParadise repo.** Suggested name
`session-capture-exporter` (not "seshmagic-*"): the rename is the point, since a
workspace image cannot depend on a binary named for one vendor's product.

Its own repo rather than a directory inside agentic-primitives, for three
reasons that all point the same way:

- **One responsibility.** It reads local transcripts and POSTs conformant
  envelopes. That is the whole job, and it is testable against the standard's
  conformance suite without any of agentic-primitives' Docker surface.
- **Cross-platform is a first-class requirement, not a container detail.** The
  same binary is the Source on a laptop and a VPS, which is where the live
  corpus already comes from. Its release matrix is therefore
  linux/{amd64,arm64} + darwin/{amd64,arm64} + windows/amd64, not just the two
  Linux targets the workspace image needs. A repo whose CI matrix is five
  targets does not belong inside a repo whose CI builds Docker images.
- **Independent release cadence.** Consumers pin a released artifact by version
  and digest. Coupling its releases to agentic-primitives' would force an image
  rebuild for an exporter patch and vice versa.

It depends on the standard crate and implements EX01. That dependency is the
only coupling it should have.

**2.2 Genericize the surface.** Binary name, env var prefix, and help text carry
no vendor identity. It POSTs conformant envelopes to whatever URL it is given.

**2.3 Conform to EX01.** Implement `--version` (G3), reject unknown flags, and
implement the exit-code table. Add file-based credential delivery.

**2.4 Cross-platform signed release pipeline.** linux/{amd64,arm64} for the
workspace image, darwin/{amd64,arm64} and windows/amd64 for the laptop and VPS
Source case. cosign keyless, published as release artifacts. Today only a
Mach-O arm64 build exists; there is no Linux amd64 binary anywhere, which is
also why the container path has never run outside one developer's machine.

**2.5 SeshMagic keeps the receive side**, adds the standard's crate at 2.0.0, and
switches its four `Origin` struct literals to `Origin::new(...)`.

**Exit criteria:** a public repo builds a signed multi-arch binary that passes
the EX01 conformance suite.

## Phase 3: agentic-primitives consumes both

**3.1 Fix G1 and G2 first.** They are independent of everything else and block
all execution, not just capture. G2 in particular affects EVERY capability and
misreports its own cause.

- G1: tmpfs for `/spool` in `agentic_isolation/config.py` alongside the existing
  `/tmp` and `/home/agent` entries.
- G2: `entrypoint.sh:429-437` must distinguish "audit dir unwritable" from
  "checks failed", and `/var/agentic` must be writable.

**3.2 Bake the binary (G4).** `COPY --from` a pinned release artifact of the
public exporter into the workspace images. Rejected alternative: bind-mounting
from the Docker host. `WorkspaceConfig.mounts` / `MountConfig` / `with_mount()`
already exist in agentic-primitives and are **dead code** (`providers/docker.py`
never reads `config.mounts`), so it is not "already supported"; and it makes the
workspace depend on host filesystem layout, which breaks the moment a workspace
runs anywhere but one machine, and does not solve multi-arch.

**3.3 Depend on the standard rather than reimplementing it.**
`lib/python/agentic_session_store/contract.py` hand-rolls the contract; the
standard says consumers depend on the crate so drift is a build failure. The
standard is Rust-only, which is why the reimplementation happened. Recommended:
generate the Python types from `schemas/session-envelope.schema.json` at build
time with a CI drift check. Rejected: publishing a Python package from the
standards repo (a second release pipeline for one consumer).

**3.4 Add the deployment slot (G8).** `AGENTIC_SESSION_STORE_DEPLOYMENT` in
`Env`, exported as `SESSION_STORE_ORIGIN_DEPLOYMENT` in `init.sh`. Name it for
DEPLOYMENT: `environment` already exists and means the runtime class, and
overloading it is the drift this whole arc is correcting.

**3.5 New image digests**, and the signing policy updated to match.

**Exit criteria:** a workspace container with the capability enabled passes all
five doctor checks at preflight and produces a real upload.

## Phase 4: Syntropic137 integration

**4.1 Bump the submodule and the pinned digests** in `workspace_images.py`. The
existing `TestEveryProviderIsPinned` guard means a missing pin fails the suite
rather than at provision.

**4.2 Send the deployment (G8, syn137 half).** `session_store_env.py` builds
`AGENTIC_SESSION_STORE_DEPLOYMENT` as `syntropic137__<app_environment>` from the
existing `AppEnvironment` StrEnum, which already drives the agent network name
and vault selection. No new configuration surface.

**4.3 Refuse URL-without-token (G6).** `SessionStoreSettings.is_enabled` gates on
URL alone and deliberately excludes the token. With a URL and no token every
doctor check passes, the workspace starts, and finalize reports a bare
`failed=1` with the diagnostic suppressed by design. Add a model validator that
rejects the combination at startup rather than losing sessions silently.

**4.4 Network path (G5).** The store must be reachable from the workspace
container. Note the egress framing in the docs is wrong and should be corrected:
`agent-net` is NOT internal, workspace containers have unrestricted outbound, and
Envoy is a credential-injection path reached by base-URL redirection, not an
egress control. So no allowlist entry is needed; what is needed is a resolvable
address. Use an address Docker's resolver can answer.

**4.5 Vault fields.** `SYN_SESSION_STORE_URL` and `SYN_SESSION_STORE_AUTH_TOKEN`
on the `syntropic137-config` item in `syn137-dev` and `syn137-beta`. No code
change: the API image bakes `op`, and `inject_fields` injects every field by
label.

**Exit criteria:** one workflow run, one session in the store, tagged
`syntropic137__dev`, retrievable by ID.

## Phase 5: prove it

**5.1 First light.** A codex phase declaring a bundled skill: the run completes,
`skills list --agent codex` inside the container shows the skill installed, and
the session is queryable in the store.

**5.2 Run it twice.** The second sweep must report `skipped_unchanged` and the
store must hold one row, not two. This is the only thing that exercises the
exporter state file, and it had never been exercised before AP #303's final run.

**5.3 Both harnesses.** Codex has never been run against the session store at
all. AP #303's verification was Claude-only, one session, one partition, against
a test rig rather than a live store, with an exporter binary no deploy ships.
Budget a fix round here rather than treating it as a formality.

**5.4 Restart safety.** Kill a workspace mid-run and confirm the failure mode is
understood and acceptable (see G7 below).

## Explicitly deferred, with reasons

- **G7 spool durability.** The spool is tmpfs-backed and dies with the container;
  finalize gets roughly a 2-second budget on the `docker stop` path. Worse,
  `reconciliation.py` reaps orphans with `docker rm -f` and no stop first, so any
  workspace reaped there loses its sessions unconditionally. **The `docker stop`
  one-liner in the reaper should be fixed now** (it is a one-line change and
  prevents unconditional loss); durable spool storage across container lifetimes
  is a design task and should not gate first light.
- **G9 credential exposure.** The write token is a container env var, and the
  entrypoint's withhold mechanism is a no-op under Syntropic137's `docker exec`
  execution model, so the agent can read it. This is the same class as the
  already-tracked ADR-024 reversal (#723/#724/#725). Phase 1's file-based
  credential requirement is the enabler; the fix lands after first light.
- **Provider-specific doctor.** `seshmagic/doctor.sh` is never invoked, so the
  state-file validity check never runs in production.

## Sequencing

```
Phase 1 (APSS substandard) ──┐
                             ├──> Phase 3 (AP) ──> Phase 4 (syn137) ──> Phase 5
Phase 2 (extract+publish) ───┘
```

Phases 1 and 2 are parallel. Phase 3.1 (G1/G2) is parallel with everything and
should start immediately: it is small, it blocks all execution rather than just
capture, and it needs nothing from the other phases.

## Risks

- **Phase 2 has never been done.** No Linux build exists, no signing pipeline
  exists, and the destination repo does not exist. This is the long pole.
- **Codex against the store is entirely unproven.** Not "lightly tested" -
  never run.
- **A new image digest invalidates the existing pins** in three places, and the
  signature policy must be updated in step or provision fails closed.
- **None of this blocks the Syntropic137 release**, which ships with capture off.
  It must stay off until Phase 4 completes: enabling it today hard-fails every
  workspace at preflight rather than degrading, because the capability is
  fail-closed and there is no binary.

## References

- `docs/handoffs/20260818-handoff_ap-session-store-standard-dependency.md`
- `docs/handoffs/20260818-handoff_seshmagic-exporter-extraction.md`
- `docs/handoffs/20260818-handoff_apss-session-capture-changes.md`
- AgentParadise/agent-paradise-standards-system#133
