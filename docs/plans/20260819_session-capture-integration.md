# Plan: make session capture work in Syntropic137 workspaces

**Date:** 2026-08-19
**Status:** v1 reviewed NO-GO by codex; v2 in revision
**Availability policy:** DECIDED - see below
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

## Availability policy (user decision, 2026-08-19)

**Capture MUST NOT block agent execution.** A store outage, a DNS failure, or an
expired token must never stop a workflow from running. Uptime of the platform is
not to be coupled to uptime of the session store.

This overrides the review's recommendation to add an authenticated
write-readiness check to the fail-closed preflight. The reasoning behind that
recommendation is still valid and is answered differently below, not ignored.

Three consequences, and they are the design, not caveats:

**1. The session-store doctor checks become NON-FATAL.** Today every capability
doctor failure hard-fails the workspace before agent work starts
(`workspace/entrypoint.sh:420`). For this capability that is the wrong trade:
it converts "we cannot record what happened" into "nothing happens at all".
The capability needs a degraded mode, which the entrypoint's current
all-or-nothing contract does not express. Note this is a change to the ADR-040
capability contract, not just to one adapter, and it is the single largest
correction from v1.

**2. A clear indicator is REQUIRED, because fail-open without one is silent data
loss.** This is the part that makes fail-open safe rather than negligent. The
platform must be able to answer, per execution: was capture attempted, did it
succeed, and if not why. Concretely:
- doctor outcome recorded as an observability event, not only as a container log
  line, and surfaced on the session/execution view
- finalize result parsed into structured counts (discovered / uploaded /
  accepted / rejected / failed) rather than reconstructed from stderr text
- a visible state per execution: `captured`, `pending`, `failed`, `disabled`
- the failure reason carried through, without leaking the credential

**3. Backfill is a first-class requirement, not a recovery afterthought.** Since
a run can complete with its capture unsent, there must be a supported path to
send it later. A manual script is acceptable for v1 - the user explicitly said
so - but it must exist before capture is enabled anywhere real, and it must be
able to reach the transcripts of a workflow that has already finished.

That last clause is the hard part and it interacts with G7: if the spool is
tmpfs and dies with the container, there is nothing left to backfill FROM. So
fail-open does not remove the durability requirement, it sharpens it. Backfill
needs a durable artifact. The candidates are the existing artifact storage
(MinIO, which already receives per-execution artifacts) or a host-side spool.
**Deciding that source is now the first design task of Phase 3, not Phase 5.**

## Durable spool: DECIDED - host-backed `/workspace`, collected to MinIO

The open question was where transcripts live so they survive a container that
dies before uploading. The answer is that the durable path already exists and
the spool simply is not on it.

- `/workspace` is a **host bind mount** (`providers/docker.py`,
  `-v {workspace_dir}:/workspace:rw`). Anything written there outlives the
  container by construction.
- `/spool` is tmpfs (as of agentic-primitives #345) and is RAM-backed, so it
  dies with the container. That fix made the capability FUNCTION; it did not
  make it durable, and was never claimed to.
- Syntropic137 already collects `artifacts/output/**` out of `/workspace` into
  MinIO via `ArtifactCollector.collect_from_workspace`. That is the existing
  machinery, already wired, already tested.

**Decision:** transcripts land under the host-backed workspace directory, and
Syntropic137 collects them into MinIO alongside artifacts. Backfill then reads
from MinIO and POSTs to the store - a script, not a new subsystem, which is what
the user asked for.

Consequences worth stating:

1. **No new storage system.** No host spool directory to quota, own, or garbage
   collect; no new volume lifecycle. This was the main cost of the alternative.
2. **Ordering matters.** `destroy()` deletes the host workspace directory
   (`providers/docker.py`, `shutil.rmtree`). Collection must happen before
   destroy - which it already does in the normal flow - and the reaper must not
   force-remove a workspace whose transcripts have not been collected.
3. **The prune hazard is gone.** An earlier agentic-primitives design rejected
   `/workspace` as a spool location because the capability's prune could escape
   its partition (`SPOOL=/workspace PARTITION=repos` -> `rm -rf /workspace/repos`).
   That prune was REMOVED in AP #303 precisely because it caused data loss, so
   the objection no longer applies. Do not reintroduce a prune.
4. **This is what makes fail-open safe.** A store outage now costs a delayed
   upload rather than a lost session, because the transcript is in MinIO
   regardless of whether the in-container upload succeeded.

## Archive destination: a PRIVATE collector, not the deliverable path

The "DECIDED" section above said transcripts land under host-backed
`/workspace` and are collected to MinIO by the existing machinery. A codex
review showed that "the existing machinery" is the wrong machinery, because the
only collected path is `artifacts/output/**` - the agent's DELIVERABLE
directory, which `workspace_prompt.py` explicitly tells the agent is its output
location.

Three options were considered. Spooling under `artifacts/output/` is REJECTED:
it would publish agent transcripts as workflow deliverables, expose them through
the artifact APIs to anyone who can read outputs, and - worst - a transcript
could become the `first_content` injected into the next phase, feeding a
conversation log back into the agent as if it were work product.

Spooling elsewhere under `/workspace` without collection is also REJECTED:
`destroy()` deletes the host workspace directory with `shutil.rmtree`, so the
data survives the container and then dies minutes later, which is durability
theatre.

**Decision: a separate INTERNAL collector.**

- Spool at `/workspace/.syn/session-capture/<partition>/`.
- Upload raw bytes to a private MinIO prefix, distinct from the artifact bucket.
- Record a manifest: execution and workspace IDs, object keys, content hashes,
  capture state, backfill state.
- Do NOT create artifact aggregates, do NOT return these as phase artifacts, do
  NOT list them as deliverables, and do NOT let them reach `first_content`.
- Transcripts are more sensitive than deliverables, so retention, access
  control, and deletion rules are part of this work rather than a follow-up.

**The "no new lifecycle" claim was too strong.** If archival fails, destroying
the workspace still destroys the only copy. Teardown therefore has to become
ordered rather than combined:

```
stop / finalize
  -> read authoritative status
  -> archive the private spool
  -> confirm the archive is durable
  -> remove the container
  -> delete the host workspace
```

That requires splitting today's combined `destroy()`, and requires the reaper to
follow the same order rather than removing containers outright.

## The capture verdict must come from the host, not from container stdout

`ObservationType.SESSION_CAPTURE` and a defensive parser both exist, but nothing
calls `parse_capture_status`, so no observation is ever written. The obvious fix
is to read the finalizer's line out of the container's output, and
`SupportsWorkspaceLogs` (agentic-primitives #355) makes that mechanically
possible.

**It is not sufficient, and the reason is trust.** The agent and the finalizer
run as the SAME Unix user in the omni image. Anything the agent can print, it
can forge - including a convincing `upload complete (uploaded=1)` line. The
parser's own header already admits the stream is untrusted. Moving to a status
file inside `/workspace` does not fix it either: that path is agent-writable, so
the agent can pre-create or overwrite the file.

So a `captured` state derived from container output is unverified by
construction, and recording it as authoritative would make the indicator worse
than absent: it would assert a session was stored when it may not have been.

**Required shape:**

- After agent execution ends, the HOST invokes the exporter as a distinct,
  host-controlled operation.
- The host captures that invocation's versioned JSON result and its real process
  exit status - a channel the agent has no handle on.
- The host writes the `SESSION_CAPTURE` observation from that result.
- Where practical, verify against the store by execution and deployment tag,
  which is the only fully independent confirmation.

Container-log parsing stays as a diagnostic fallback. It may produce `UNKNOWN`
or an explicitly unverified outcome; it may never be the sole basis for
`CAPTURED`.

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

**2.1 Move the crate to its OWN public AgentParadise repo:
`agentic-session-exporter`.** The rename is the point, not incidental: a
workspace image cannot depend on a binary named for one vendor's product. The
name also matches the existing family - `agentic-primitives`, `agentic-memory`,
`agentic-isolation`, `agentic-events`, `agentic-logging`.

**One adjacency to keep straight, because the names are one word apart.**
agentic-primitives already ships `lib/python/agentic_session_store`. These are
different things and neither should absorb the other:

| | `agentic_session_store` (in agentic-primitives) | `agentic-session-exporter` (new repo) |
|---|---|---|
| What | The `AGENTIC_SESSION_STORE_*` contract types and the five-check doctor | The binary that reads transcripts and POSTs envelopes |
| Where it runs | In-image, at workspace preflight | In-image at finalize, AND on laptops and VPSes |
| Language | Python | Rust |
| Profile | none - it validates the environment | implements the standard's Exporter profile |

The doctor CHECKS that an exporter is present and healthy; the exporter DOES the
capture. G3 exists precisely because those two sides had no shared contract, so
keeping the distinction sharp in naming and docs is part of the fix.

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

**4.3 Surface URL-without-token (G6). ADJUDICATED: warn, do not refuse.**
`SessionStoreSettings.is_enabled` gates on URL alone and deliberately excludes
the token. With a URL and no token every doctor check passes, the workspace
starts, and finalize reports a bare `failed=1` with the diagnostic suppressed by
design.

This plan originally said to REJECT that combination at startup. Shipped
behaviour warns instead, and the warning is correct: an unauthenticated store on
a trusted network is a legitimate deployment, and refusing would invert the
fail-open policy for operators who chose it deliberately. Refusing would also
mean a store that later ADDS auth turns a warning into a hard startup failure
for every deployment that had been working.

What makes warning sufficient is that it is loud and it names the consequence at
the point of injection, rather than leaving an operator with a bare failure
count. See `session_store_env.py`. Do not "fix" this back to a rejection.

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

- **G7 spool durability. NO LONGER DEFERRED - see "Durable spool: DECIDED".**
  This entry previously said durable storage "should not gate first light",
  which contradicted the requirement earlier in this document that backfill
  exist before capture is enabled anywhere real. A codex review flagged the
  contradiction. Resolution, in favour of the stricter reading:

  Backfill needs something to read FROM. The spool is tmpfs and dies with the
  container, so today there is nothing. Fail-open does not soften that, it
  sharpens it: a policy of tolerating failed uploads is only safe if the
  transcript still exists afterwards. So durable archive plus a backfill path
  gate REAL enablement (any deployment whose sessions we care about), while a
  throwaway dev stack may still run without them.

  The `docker stop` fix in the reaper has landed and prevents unconditional
  loss on the orphan path. It is necessary and not sufficient: the reaper still
  removes containers without archiving the host-backed spool, so orphan
  recovery archives nothing. That is tracked with the archival work below, not
  separately.
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
