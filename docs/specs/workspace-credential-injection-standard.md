# Workspace Credential Injection Standard (APSS candidate)

Status: STANDARD DRAFT (operator, 2026-06-22). Part of the Agent Workspace
Standard (docs/specs/agent-workspace-standard-VISION.md). Evidence:
~/swarm-tasks/codex-auth-injection.md + ~/swarm-tasks/codex-refresh-durability.md
(source-verified against openai/codex). Ultimate home: the Agent Paradise
standard system (APSS); promote when firm.

## 1. Purpose

Define how a workspace authenticates an agent harness, supporting BOTH static
API keys AND subscription Max-plan OAuth (Claude Max, Codex Max), in a
harness-agnostic, conformance-checkable way. The workspace MUST be explicit
about which mode each harness uses. API keys are the easy 80 percent but do NOT
get you onto the Max plans the operator pays for; the standard must support both.

## 2. The two modes (a workspace declares which, per harness)

MODE A - API KEY (easy, billing = usage-based Platform/API):
  A static secret injected at the NETWORK boundary via Envoy ext_authz. The
  agent never holds the secret; Envoy rewrites the outbound request. No
  credential lifecycle. This is the path that already works for Anthropic.

MODE B - SUBSCRIPTION MAX OAUTH (the real work, billing = subscription plan):
  The harness CLI owns its own OAuth lifecycle (it refreshes its own token), so
  the credential cannot be a network injection - it is MOUNTED into the harness's
  expected on-disk location. Lifecycle quirks (token rotation) are handled inside
  the per-harness adapter.

## 3. The CredentialAdapter interface (the standard surface)

Per harness, mode-selectable. Given (harness, mode) it returns an injection spec:
- Mode A: { token_type, env_or_header } -> the Envoy sidecar vends it (the agent
  sends no token; the proxy injects it).
- Mode B: { mount: {source_authority, container_path, rw|ro}, lifecycle:
  {refresh_strategy, lock_strategy}, recovery: {detect_signal, quarantine,
  reauth_command, propagation} }.
This mirrors the per-harness adapter registry pattern used by the observability
HarnessExporter adapters and the interactive-tmux per-agent adapters: one
interface, a thin adapter per harness, dependency-injected.

## 4. Per-harness matrix

| Harness | Mode A: API key (Envoy) | Mode B: Max OAuth (mount) | Refresh-token rotation |
|---|---|---|---|
| Claude | ANTHROPIC_API_KEY | mount ~/.claude (+ ~/.claude.json); or CLAUDE_CODE_OAUTH_TOKEN | forgiving (copy works today) |
| Codex | OPENAI_API_KEY (Platform billing) | live read-write ~/.codex + flock | SINGLE-USE ROTATING (the hard one) |
| Gemini | GEMINI_API_KEY | mount ~/.gemini | non-rotating (Google default) |
| Cursor | API key | session/OAuth (UNVERIFIED) | UNVERIFIED |
| PI | configurable (multi-provider) | OAuth per chosen provider | per provider |

The operator or workflow config selects the mode per harness per deployment:
"use the Max plan" -> Mode B mount; "use an API key" -> Mode A Envoy. Both
coexist behind one adapter interface.

## 5. Codex Max: durability (the hard adapter)

Mechanism (source-verified, openai/codex codex-rs/login): auth.json holds
TokenData {id_token, access_token, refresh_token, account_id}. Access token TTL
about 10 days (server policy), id_token about 1 hour. Codex refreshes proactively
when access-token expiry <= now + 5 min, or on a 401; it POSTs the refresh token
to auth.openai.com/oauth/token, receives REPLACEMENT access + refresh tokens, and
writes them back. The OLD refresh token is then invalid (single-use rotation);
reuse returns refresh_token_reused (RefreshTokenFailedReason::Exhausted) = the
"refresh token already used, please sign in again" error.

Durability rule (Mode B, Codex):
- ONE live writable credential AUTHORITY per operator account (the box's own
  ~/.codex via `codex login --device-auth`). NO copies.
- Mount that authority read-WRITE into the workspace (so refreshes persist).
- Wrap EVERY codex launch in a host-visible flock held for the process lifetime:
    flock /home/agent/.codex/.auth.lock codex exec --json ...
  so concurrent Codex processes serialize their refresh attempts and all observe
  the latest auth.json. This eliminates the rotation race for one box and for N
  serialized consumers.

## 6. Recovery flow (a first-class standard concern)

An invalidated rotating refresh token CANNOT be refreshed programmatically; the
only fix is re-login. Every Mode-B adapter MUST declare a recovery flow; Codex's
is the worked example:
1. DETECT: codex returns refresh_token_reused / refresh_token_expired /
   refresh_token_invalidated. A workspace health probe (doctor-style) checks for
   this proactively.
2. QUARANTINE: stop all codex processes on that credential chain; remove stale
   copies.
3. RE-LOGIN ONCE ON THE AUTHORITY: `codex login --device-auth` on the single
   live ~/.codex. Device-auth is headless-friendly: it prints a URL + code; the
   operator authorizes in any browser; codex writes a fresh auth.json + chain.
4. PROPAGATE FOR FREE: because every workspace MOUNTS the live authority (not
   copies), the fresh token is picked up automatically by all workspaces. No
   per-container re-auth.
The single-authority + live-mount design is precisely what turns recovery into a
one-shot operator action instead of an N-container nightmare.

## 7. Future: credential broker (Mode B, multi-workspace scale)

For many truly-concurrent workspaces, a BROKER owns auth.json + the refresh and
vends only SHORT-LIVED ACCESS tokens to containers (containers never hold or
refresh the refresh token) - architecturally the cleanest, analogous to the
Anthropic Envoy token-injector. Blocked today because codex expects to own
auth.json; upstream has an experimental `chatgptAuthTokens` external-auth path
(accepts an access token + ChatGPT account metadata, stores no refresh token) but
it is internal/unstable. Track it; adopt when it stabilizes. Until then,
single-authority + flock is the durable answer.

## 8. APSS encoding / conformance

- A workspace DECLARES its credential capability in a manifest: which harnesses x
  which modes it supports.
- A conformance / fitness check verifies: every Mode-A harness has an Envoy route;
  every Mode-B harness has a mount spec; every rotating Mode-B harness (Codex) has
  a lock strategy AND a declared recovery flow with a health probe.
- "The workspace is clear about the modes" = the manifest is explicit and
  validated by the conformance check. That is the APSS hook.

## 9. Recommended near-term work

1. Fix the interactive-tmux driver Codex auth: copy-to-throwaway -> live
   read-write ~/.codex mount + flock wrapper (kills "refresh token already used").
2. Add a Codex-credential health probe (detect refresh_token_reused) to the
   workspace doctor.
3. Implement the CredentialAdapter interface (Mode A Envoy + Mode B mount) as the
   credential plank of the Workspace Standard, starting with Claude + Codex.
4. Defer the broker until codex stabilizes external-auth.

## 6b. Easy remote re-login (no env var, no SSH, one tap)

Syntropic137 runs on a remote box, so re-auth must NOT require pushing a secret
or env var to the box - and it does not. The Codex credential is a FILE on the
authority (~/.codex/auth.json), and device-auth is designed so the operator
authorizes from a DIFFERENT device than the one being authed. The flow:

1. DETECT (automatic): a credential watcher / the workspace doctor sees
   refresh_token_reused on the authority and marks Codex Max degraded.
2. AUTO-TRIGGER: a service/recipe runs `codex login --device-auth` on the box and
   captures the verification URL + user code.
3. NOTIFY (pager): push the URL + code to the operator's pager channel (NTFY,
   pager-only per Syntropic137 notification routing): "Codex Max auth expired -
   tap to re-authorize: <url> (code <code>)".
4. OPERATOR APPROVES: taps the link on a phone or laptop, signs into ChatGPT,
   enters the code. About 15 seconds, from anywhere - no SSH.
5. BOX COMPLETES: device-auth finishes and writes a fresh auth.json to the single
   live authority.
6. PROPAGATE: the live mount means every workspace picks up the fresh token
   automatically. No env var pushed, no secret sent to the box, no per-container
   action.

Manual trigger: a `just codex-reauth` recipe (or a dashboard button / endpoint)
runs the same device-auth + notify flow on demand.

This is the decisive reason the OAuth-mount + device-auth design beats a
token-injection design for a remote box: with env-var / token injection the
operator WOULD have to push a new secret to the remote and every container on
every rotation; device-auth pushes NOTHING - the box self-services its own
credential after a single approval tap. The standard therefore REQUIRES every
rotating Mode-B adapter to expose: an auto-detect probe, a one-command/one-tap
re-auth trigger, and a notification delivery of the authorize-from-anywhere
prompt. Recovery is a pager tap, never a secret hand-off.
