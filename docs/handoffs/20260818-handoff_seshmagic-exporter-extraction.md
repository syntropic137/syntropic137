# Handoff: extract the session exporter so it can ship in a workspace image

**Date:** 2026-08-18
**Repo:** https://github.com/seshmagic/seshmagic_session_store (source) -> destination TBD
**Branch:** to be created off `main`
**Status:** ready-to-start (decision on destination org still open)

> Written from the syntropic137 side. The work is in the SeshMagic repo plus
> whichever repo the exporter lands in.

## Purpose & Vision

Nothing can capture a session inside a Syntropic137 workspace today, because the
exporter binary does not exist in the workspace image and there is no mechanism
to put it there. The workspace images deliberately refuse to vendor it:

> This image deliberately does NOT ship SeshMagicSessionExporter. The exporter is
> a reference client of the public APS-V1-0004 standard, not part of the private
> store server. Vendoring one vendor's binary into this image would break the
> store being dependency-injected.
> - `providers/workspaces/claude-cli/Dockerfile:210`

That reasoning is sound, and the fix is to stop it being one vendor's binary.
Extract it as the reference client of a public standard, published so
agentic-primitives can bake it. The store stays private and paid; the client goes
public, because users have to run it on their own machines anyway.

## Current State

- The exporter lives at `crates/seshmagic-session-store-exporter` **inside the
  private store repo**, which is exactly why agentic-primitives cannot bake it.
- It works. A real end-to-end upload was driven against the real store at
  `homelab:18090` and the session is retrievable at
  `GET /v1/sessions/probe5-0001`.
- **The only build that exists is Mach-O arm64.** A Linux aarch64 build exists at
  `target-linux/release/`. There is **no linux/amd64 build anywhere.**
- Consumers pin workspace images by digest and cosign-verify them, so whatever
  ships must be signed and multi-arch.

Next actions, in order:

1. Decide destination org (see Rationale - this contradicts the current spec text
   and needs an APSS amendment either way).
2. Genericize: it must stop being "the SeshMagic exporter".
3. Add the missing `--version` flag, or change what the consumer's doctor calls.
4. Multi-arch release pipeline: linux/amd64 + linux/arm64, signed.
5. Decide delivery into the workspace (derived image recommended).

## Files Affected

- `crates/seshmagic-session-store-exporter/src/bin/exporter.rs:32-40` - the flag
  parser. Accepts `--dry-run`, `--health`, `--loop`, `--cursor-limit` and
  **nothing else**.
- `crates/seshmagic-session-store-exporter/src/config.rs:88-89` - reads
  `SESSION_STORE_ORIGIN_ENV`, defaulting to `"laptop"`.
- `crates/seshmagic-session-store-exporter/src/config.rs:143` - comma-split tag
  parsing.
- `Cargo.toml:48` - `apss-v1-0004-session-capture = "1.0.0"`, the real dependency
  on the standard. This is the part to preserve unchanged through the move.
- `crates/seshmagic-session-store-server/src/http.rs:459,559-585` -
  `origin_environment` handling and the `app__env` rollup convention. Stays
  private; noted so the extracted client keeps sending what it expects.

## Rationale & Key Decisions

**Open sourcing the client does not mean open sourcing the store.** This is the
ordinary shape of every observability business: Sentry SDKs are open and
sentry.io is paid; the Datadog agent is Apache-2 and the backend is not. The
collector is the on-ramp, the store is the product. Charging for the pipe was
never viable because users run it locally regardless.

Publishing the client also leaks nothing, because **the wire format is already
public** - that was the point of ratifying APS-V1-0004. The moat is retention,
search, reconstitution, hosting, not the POST.

**The exporter must stop being vendor-shaped.** Today it is named
`SeshMagicSessionExporter` and reads `SESSION_STORE_URL` / `SESSIONS_WRITE_TOKEN`.
If agentic-primitives bakes *that*, a general-purpose multi-agent workspace image
acquires a dependency on one company's session-store product. Renaming it to the
reference implementation of the standard's **Exporter profile** removes the edge:
it POSTs conformant envelopes to whatever URL it is given, and SeshMagic becomes
one possible endpoint. Dependency graph becomes a tree:

```
APS-V1-0004  (public standard, the version anchor)
   |-- reference exporter   (public)  --baked into--> agentic-primitives images
   \-- SeshMagic store      (private, paid, implements the receive side)
```

Nothing depends on SeshMagic. SeshMagic depends on the standard.

**Destination org: this contradicts the spec as written.**
`APS-V1-0004/docs/01_spec.md:980-982` currently says the behavioural reference
implementation "lives in the SeshMagic repository, NOT here", and lists the
reference exporter among SeshMagic's responsibilities. Moving it to Agent
Paradise requires amending that text. Either destination works technically; pick
one and amend the spec to match, rather than leaving the spec describing a layout
that no longer exists. **Recommendation: Agent Paradise**, because the consumer
that bakes it (agentic-primitives) is there, and a client living in the private
store repo is what created this problem.

**Delivery into the workspace: derived image, not bind-mount.** Bind-mount is
tempting and cheaper, but:

- `WorkspaceConfig.mounts`, `MountConfig`, and `with_mount()` all exist in
  agentic-primitives and are **dead code** - `providers/docker.py` never reads
  `config.mounts`, so anything set there is silently dropped. The only mount
  emitted is `-v {workspace_dir}:/workspace:rw`. Enabling it is a real change.
- It makes the workspace depend on host filesystem layout, which breaks the
  moment a workspace runs anywhere but one Mac.
- It does not solve multi-arch. The host binary must match the container arch.

A derived image (`FROM <omni digest>` + `COPY`) costs a new published image, a
new digest pin, and a signing-policy entry, and solves all three.

## Do's and Don'ts (learned this session)

- **Do** add `--version`, or change what the consumer calls. The consumer's
  doctor runs `[path, "--version"]` and requires exit 0. The binary **ignores
  unknown flags and runs a full capture sweep**, so the health check currently
  passes by performing a real upload at workspace preflight, inside a 5-second
  timeout. This is the single highest-value fix in this document.
- **Don't** ship a client that requires the store's private types. The
  `apss-v1-0004-session-capture` crate dependency is what makes extraction
  possible; keep the client depending on the standard only.
- **Do** expect `origin_environment` to matter more after extraction. A generic
  client with no environment field lands every session under `"laptop"`.
- **Don't** assume the store's auth behaviour is uniform: `/healthz` is
  unauthenticated and returns 200, while `POST /v1/sessions/batch` returns 401.
  A consumer can therefore pass every health check and still fail every upload.

## Important Context to Keep in Mind

- **The credential is currently readable by the agent.** In Syntropic137's
  execution model the container runs `sleep infinity` and agents run via
  `docker exec`, which inherits the container's configured env - so the
  entrypoint's withhold mechanism does not apply and `SESSIONS_WRITE_TOKEN` is
  visible. A public client makes it worth specifying credential delivery (a
  0600 file, or finalize-only injection) rather than a container env var.
- **The spool is RAM-only and dies with the container.** Finalize runs on
  `docker stop -t 5` and gets roughly a 2-second budget, measured at 0.30s for a
  small session. Any consumer path that uses `docker rm -f` without a stop first
  loses sessions unconditionally.
- The store is tailnet-only. `homelab` does **not** resolve inside a container;
  the tailnet IP does.

## Suggested Skills

- `sdlc:git-worktree` - note its `create` action is broken on macOS (BSD sed);
  see AgentParadise/agentic-primitives#343. Use `git worktree add` directly.
- `delegation:delegating-to-codex` - cross-model review, with `< /dev/null`

## References

- `lib/agent-paradise-standards-system/standards/v1/APS-V1-0004-session-capture/docs/01_spec.md:980-995` - the text that must be amended
- `providers/workspaces/claude-cli/Dockerfile:210` (agentic-primitives) - the refusal to vendor, and its reasoning
- `docs/handoffs/20260818-handoff_ap-session-store-standard-dependency.md` - the consumer-side half
- `docs/handoffs/20260818-handoff_apss-session-capture-changes.md` - the standard-side changes
