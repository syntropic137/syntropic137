# Final plan: revise `docs/plans/20261014_credential-broker.md` (H1/H2 ALLOW, H4 transport and identity)

Revise phase, 2026-10-14. Target: `docs/plans/20261014_credential-broker.md` on branch `docs/runtime-research-20261012` (PR #1874), edited in place. **Base revision for every edit and every diff check: `f5ddc382ddcda968f3cdcc777f183ba48449a388`.** Only that one file changes. No source, config, ADR or workflow file changes.

This document stands alone. It covers the owner's decisions, the H4 recommendation and its evidence, the complete list of edits to make to the target document, the risks, how to verify the edit, and how each review finding was handled.

## How to read this document

- **Evidence labels.** **[V]** means verified by reading the file or the primary source. **[I]** means inferred. **[U]** means unconfirmed. The survey labels come from the research phase. This phase did not re-fetch external sources, so it did not upgrade any of them.
- **Two kinds of citation.**
  - Paths into this repository were re-read on the `main` checkout in this phase. Each one is cited as `path:line` from the repo root.
  - Citations of the form `docs/plans/20261014_credential-broker.md:NNN` and `docs/plans/20261013_selfhosted-microvm-pool.md:NNN` are the review's line numbers at `f5ddc382d`. Neither file exists on `main`, and this phase had no git tool to read the branch. The edit phase must find each one by its text before editing it.
- **What this phase did not do.** This phase was granted Read, Grep, Glob, Write and Skill only. It could not commit, push or read another branch. The edit, the commit and the push to PR #1874 belong to the next phase. Step 13 of the edit list below defines them.

---

## 1. Problem

1. **The OAuth refusal is now out of date.** The plan refuses Claude Max OAuth and Codex ChatGPT login on remote workspaces "until H1/H2". The owner has now allowed both. The refusal appears in the scope statement, D4, D8, S1, §9, §11 and Readiness, and no risk row covers the new posture.
   - Making OAuth a brokered class is more than deleting the refusal. It moves an account-wide credential, and for Codex a **rotating refresh token**, out of the sandbox and into the broker. The broker then has to own that credential's whole lifecycle.
   - Today the Codex credential is a static setting, `packages/syn-shared/src/syn_shared/settings/config.py:309`. It is copied into each sandbox, which then refreshes it independently: `packages/syn-adapters/src/syn_adapters/workspace_backends/service/setup_phase_secrets.py:731-751`.
2. **H4 is undecided.** The plan says a remote workspace reaches the broker through "Cloudflare tunnel or a tailnet (H4)", with box mTLS "optional" (`docs/plans/20261014_credential-broker.md:137-138`).
   - Nothing yet binds a capability to the box it was issued for.
   - The exfiltrated-capability risk row is mitigated only by an "H4 source binding" that does not exist (`docs/plans/20261014_credential-broker.md:567`).
   - PR 8 (TLS listener, `SYN_BROKER_URL`, compose/tunnel route) therefore has no design to implement.

## 2. Owner decisions recorded (not re-argued)

- **H1: ALLOW** (owner, 2026-10-14). Remote workspaces may use Claude Max OAuth through the broker, the same way local workspaces use it today.
- **H2: ALLOW** (owner, 2026-10-14). The same applies to Codex ChatGPT login.
- **Terms of service.** The terms-of-service consideration is recorded as **the owner's accepted decision**. The document states this once and does not weigh it again.
- **Stale statements left in place.** Two places in the repository still state the old posture. This change does not touch them, because the brief says "no source changes". They become follow-ups (§10):
  - `docs/adrs/ADR-024-setup-phase-secrets.md:531`: "ToS gray area precludes header proxying"
  - `packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/handlers/WorkspaceProvisionHandler.py:271`: "OAuth is out of scope (ToS gray area for header proxying)"

## 3. H4 recommendation (text for the new section, approvable in one line)

> **Approve:** With the central broker (the plan's H5 default), each remote box runs a secret-free forwarding Envoy. Sandboxes reach it in plaintext with their per-workspace capability. It reaches the central broker over the existing tailnet using a **per-box mTLS client certificate**, whose only SAN is `spiffe://syntropic137/box/<box-id>`, issued by a Syntropic137 box CA. The broker's Envoy overwrites `x-forwarded-client-cert` from the verified peer. The token injector denies any request whose capability was issued for a different box, or whose box is not on the Redis allow-list. That allow-list is checked per request, which keeps 60 s revocation. The tailnet provides reachability only, Cloudflare tunnel is not used for broker traffic, and SPIRE is not run on owned boxes. The Kubernetes binding granularity is decided at #1909.

### 3.1 Answer to the owner's question: "is tailnet plus mTLS the proper approach?"

**Yes, for owned boxes and a central broker, with two corrections to the framing.**

1. **mTLS authenticates the box, not the sandbox.** The sandbox's credential is the per-workspace capability, which is a bearer token.
   - The one surveyed platform with a visible sandbox-to-control-plane credential path, OpenHands, also uses a per-sandbox bearer. Unlike us, it hands the raw upstream key into the sandbox. Our capability is the stronger version of that bearer: it is revocable in 60 s, and the upstream secret never enters the sandbox.
   - mTLS and SPIFFE appear in the survey one layer down, as node or workload identity presented to a service: Kubernetes meshes, SPIRE, and Cloudflare Access client mTLS.
   - That layer is exactly where our remaining gap sits: replaying an exfiltrated capability from off the box.
2. **The tailnet is not the identity.** It could be one, as §5 shows: "tailnet with a reviewed policy plus source-IP binding" is the runner-up and a legitimate cheaper choice. mTLS wins on three properties the owner has said matter, and not on the claim that tailnet ACLs are unreviewable (they can be managed as code, §5):
   - the identity is checked by the broker itself, in `docker/sidecar-proxy/envoy.yaml` and the token injector, which this repository reviews and tests
   - it is independent of addressing and of every proxy or NAT on the path
   - it has a direct analogue on Kubernetes

### 3.2 Scope of the recommendation: central broker only (H5)

The recommendation is **conditional on H5 = central broker**, which is the plan's stated default (`docs/plans/20261014_credential-broker.md:618`).

**Per-box brokering is a different protocol, not a variant of this one.** In that topology:

- the box would *fetch* upstream credentials or grants from the control plane
- the sandbox would talk to a local listener that has no peer certificate
- revoking a box would not withdraw credentials it had already fetched

**OAuth in particular cannot be per box.** A rotating Codex refresh token held on N boxes means N refreshers racing for one token (§4.1).

**If the owner chooses per-box brokering for H5, H4 must be reopened.** The plan does not design that path and does not claim this recommendation covers it.

**Interaction with the microVM plan.** That plan places "Envoy and token injector" on every box (`docs/plans/20261013_selfhosted-microvm-pool.md:291`). Under this recommendation the box Envoy is a **forwarder holding no upstream secret**, and the injector runs only on the control plane. The edit adds one sentence recording that amendment. The microVM plan itself is not edited, because it is a different file and outside this change.

---

## 4. Design detail

### 4.1 OAuth credential lifecycle (H1/H2 implementation contract)

This section is the contract for the D2, D3 and D10 edits. Mechanics specific to a harness CLI stay in agentic-workspace and are proven by S1 (§4.1.5). This repository owns where the credential lives, who refreshes it and when the broker refuses.

#### 4.1.1 Class selection (D10)

The workspace requests a broker capability per **provider class**: `ANTHROPIC` for the Claude harness and `OPENAI` for the Codex harness. It requests the class in **every** auth mode, not only in API-key mode.

The class's upstream record carries an `auth_kind`, a closed enum:

| Class | `auth_kind` values |
|---|---|
| `ANTHROPIC` | `api_key`, `oauth` |
| `OPENAI` | `api_key`, `chatgpt` |

**The broker** chooses the presentation from `auth_kind`. The workspace never states it.

When both kinds are configured, precedence matches local behaviour today. Claude OAuth wins over an API key: see `packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/handlers/WorkspaceProvisionHandler.py:272-275` and `packages/syn-adapters/src/syn_adapters/workspace_backends/service/setup_phase_secrets.py:200-205`. Codex uses ChatGPT mode exactly when `codex_auth_json` is configured.

The edit replaces the D10 rule that requests `OPENAI` only for Codex API-key mode (`docs/plans/20261014_credential-broker.md:232`).

#### 4.1.2 Residency (D3)

OAuth upstream state lives **only on the control plane**:

| Item | Where it lives |
|---|---|
| Durable record | `upstream_oauth_state`, one per account, in the control plane's Postgres, encrypted at rest with a key held in the injector's environment |
| Cache of the current access token | Redis, TTL equal to the token's expiry |
| In the sandbox | nothing |
| On a remote box | nothing |

This extends D3 (`docs/plans/20261014_credential-broker.md:97`, `:101`), which today places model API keys in the injector environment and GitHub tokens in grants. Postgres, not Redis, holds the durable record, because a rotated refresh token that is lost cannot be recovered without a human logging in again.

#### 4.1.3 Import

- **Seed values.** The existing settings are the seed:
  - `CLAUDE_CODE_OAUTH_TOKEN` (`packages/syn-shared/src/syn_shared/settings/config.py:288-297`)
  - `CODEX_AUTH_JSON` (`packages/syn-shared/src/syn_shared/settings/config.py:309`)
- **First import.** On injector start, if no durable record exists for the account, the seed is imported.
- **After that, the durable record wins.** A seed that differs from it is logged as a warning and ignored. It is never silently re-imported, because doing so would revive a refresh token the broker has already rotated away.
- **Re-import.** Re-import is an explicit operator action. The PR that implements this defines the command.

#### 4.1.4 Refresh ownership

- **Codex (`chatgpt`).** The control-plane token injector is the **only** refresher.
  - **Single-flight.** Before refreshing, the injector takes a Redis lock (`SET NX PX`) keyed by account. Concurrent requests either wait for the refresh or use the still-valid current access token.
  - **On success.** The refreshed access token and refresh token are written to the durable record before the lock is released.
  - **On failure.** The injector raises an alert and denies with the distinct reason `upstream_oauth_refresh_failed`. It does not retry in a loop.
  - **If Redis is unavailable,** refresh fails closed. This follows the CLAUDE.md rule against silent in-memory fallback.
- **Claude (`oauth`).** **[U]** whether the token produced by `claude setup-token` is refreshable or just long-lived. The plan treats it as a static bearer:
  - The broker does not refresh it.
  - An upstream 401 maps to the distinct deny reason `upstream_oauth_expired` and raises an alert.
  - The operator re-seeds the token.
  - S1 gate (c) settles this.
- **Account exclusivity.** A ChatGPT account brokered remotely must not also be logged in, outside the broker, anywhere that refreshes the same token. A local `~/.codex` for the same account counts. This is the owner's decision 4 (§11).

#### 4.1.5 Presentation and S1 gates (agentic-workspace work, observable results)

Each gate is stated as a result someone can observe:

- **(a) Claude, initial presentation.** The pinned Claude CLI is given a capability in the `CLAUDE_CODE_OAUTH_TOKEN` slot and `ANTHROPIC_BASE_URL` pointing at the broker. It sends the capability in a header the broker can overwrite with `authorization: Bearer <oauth>`, and a full turn succeeds.
  - Background: the CLI validates credential format locally (`packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/handlers/WorkspaceProvisionHandler.py:262-265`). The capability may therefore need an OAuth-shaped format. That is harness knowledge and belongs in agentic-workspace.
- **(b) Codex, initial presentation.** Codex in ChatGPT mode, given the auth-file shape agentic-workspace defines, completes a turn through the broker. That auth file contains a capability and **no real access token or refresh token**.
- **(c) Expiry and refresh.**
  - Force the upstream access token to expire, then run 10 concurrent turns through the broker.
  - Pass condition: exactly one upstream refresh is recorded, and every turn succeeds.
  - Afterwards, a scan of the sandbox filesystem and environment finds neither the initial nor the refreshed upstream token.
  - If the harness tries to refresh by itself, that attempt is denied by egress (no route to the auth host) or by the broker, and the turn still succeeds.
  - For Claude, (c) establishes which branch of §4.1.4 applies.
- **If a gate fails,** that class stays `HostCredentials`-only on remote, as D8's fallback sentence already says. The owner is told the decision was made but cannot be implemented for that harness.

### 4.2 Transport topology (central broker)

```
sandbox --plaintext + capability--> box Envoy (forwarder, no secrets)
        --tailnet, mTLS (per-box client cert)--> broker Envoy (remote listener)
        --ext_authz HTTP, restricted internal network--> token injector (control plane)
        --upstream TLS--> provider
```

- **TLS terminators.**
  - The box Envoy is a TLS client to the broker. It verifies the broker's server certificate against the Syntropic137 CA, with SAN `spiffe://syntropic137/broker` and a pinned SNI.
  - The broker Envoy's remote listener terminates mTLS with `require_client_certificate: true`. The trusted CA is **only** the Syntropic137 box CA, never the system roots.
- **Credential residency.** Upstream secrets exist only on the control plane (§4.1.2). The box Envoy holds its own box key and certificate, and nothing else.
- **Authorization point.** The token injector on the control plane, on every request.
- **Box revocation.** Deleting the box from the Redis allow-list denies the box's next request through the existing per-request lookup (D2, D11), on any connection, including one already open.
  - A model stream already in flight runs until it finishes or reaches the 300 s route timeout (`docker/sidecar-proxy/envoy.yaml:184`).
  - This is the same bound that already applies to capability revocation, and the edit states it explicitly.
- **Control-plane disconnection.** The box holds no credentials, so a disconnected box can do nothing. Requests fail closed (`failure_mode_allow: false`, `docker/sidecar-proxy/envoy.yaml:269`).
- **Local workspaces.** The local workspace keeps the existing plaintext listener (`docker/sidecar-proxy/envoy.yaml:74-78`) and the URL default `http://envoy-proxy:8081` (`packages/syn-adapters/src/syn_adapters/workspace_backends/service/workspace_service.py:266`). The capability check runs there too (§4.3), so D5's "one code path; only the URL differs" holds, with no "local is trusted" branch.
- **Tailnet cold path.** The cold-path behaviour is unchanged: about 7.2 s cold against 0.017 s warm (`docs/handoffs/20260903-queued_after-vps-restart.md:155-161`). The box Envoy's broker cluster gets connect retries with backoff, and TCP keepalive on its pooled connections.

### 4.3 Identity handoff (Envoy to injector) and its validation

**Why this needs specifying.** The existing ext_authz is the **HTTP** service (`docker/sidecar-proxy/envoy.yaml:253`). It forwards only `host` and `x-forwarded-host` to the injector (`docker/sidecar-proxy/envoy.yaml:258-262`), and the injector reads only the Host header (`docker/token-injector/token_injector.py:151-153`). Adding downstream mTLS does not by itself make the peer identity visible to the injector. The design therefore names one trusted handoff.

**The handoff:**

1. **Listener kind is set by configuration, never by the client.** Each listener uses its own ext_authz `http_service.path_prefix`:
   - `/authz/local` on the existing plaintext listener
   - `/authz/remote` on the new mTLS listener

   The injector reads the listener kind from the leading path segment, which the client cannot set.
2. **The peer identity is overwritten by Envoy.** On the remote listener, the HTTP connection manager sets:
   - `forward_client_cert_details: SANITIZE_SET`
   - `set_current_client_cert_details: { uri: true }`

   Envoy then **replaces** any client-supplied `x-forwarded-client-cert` with one derived from the verified peer certificate. `x-forwarded-client-cert` is added to the ext_authz `allowed_headers`. The local listener keeps the default `SANITIZE`, which strips the header.
   - The box Envoy's own HCM also strips any XFCC header the sandbox sent, so a forged header is removed twice.
   - **[I]** That HCM applies the XFCC mutation before the ext_authz filter sees the request headers. Acceptance case 4 below proves or disproves it.
3. **The Envoy-to-injector path is restricted.** The injector listens only on the control plane's internal Docker network. Nothing on that network other than the broker Envoy can reach port 9002. A compose network check in PR 8 asserts this.
4. **Validation in the injector:**
   - On a `remote` request, it requires exactly one XFCC element, carrying exactly one `URI=` value that matches `^spiffe://syntropic137/box/[a-z0-9-]{1,63}$`.
   - On a `local` request, it requires the header to be absent.
   - Anything else is denied with reason `peer_identity_invalid`.
   - Envoy enforces the trusted issuer, because the listener's validation context trusts only the box CA, and adds `match_typed_subject_alt_names` with the URI prefix `spiffe://syntropic137/box/`.
5. **The authorization interface gains the peer.** The planned `authorize(presented, token_type, route)` (`docs/plans/20261014_credential-broker.md:376`) becomes `authorize(presented, token_type, route, peer)`. `peer` is a frozen Pydantic value object `BrokerPeer(listener: Literal["local", "remote"], box_id: BoxId | None)`.
   - The comparison: the grant's `box_id` must equal `peer.box_id`.
   - Grants issued for local workspaces carry the reserved `box_id` `local`, and match only `listener == "local"`.
   - A remote box can never be named `local`, because the SAN regex above is applied at enrolment as well.
   - Deny reasons are distinct, so a mismatch is never misread as a capability revocation:
     - `box_mismatch`
     - `box_not_allowed`
     - `peer_identity_invalid`
6. **Where `box_id` comes from at issue.** It is the **control plane's placement record**: the box the provisioner scheduled the workspace onto. It is never a value sent by the box or the workspace.
   - The grant record gains `box_id` beside the existing workspace and execution fields (`docs/plans/20261014_credential-broker.md:91`).
   - The allow-list key `broker:box:<box_id>` is written only by operator enrolment.

**Acceptance cases for PR 8.** They run against real Envoy and the real injector, using two test boxes, A and B:

1. A certificate with an A grant succeeds.
2. B certificate with an A grant gets 403 `box_mismatch`.
3. No client certificate, or a certificate from an untrusted CA, fails the handshake. A certificate that has a valid chain but a non-matching SAN is rejected by Envoy.
4. A forged `x-forwarded-client-cert: URI=spiffe://syntropic137/box/A`, sent by a sandbox on box B with a B certificate and an A grant, gets 403.
5. A forged XFCC header on the local listener gets 403 `peer_identity_invalid`, or is stripped and then denied for an A grant.
6. Deleting A from the allow-list, while a connection stays open, makes A's next request fail with `box_not_allowed` within 60 s.
7. A `local` grant presented on the remote listener gets 403.

**Mutation requirement.** Replacing the `box_id` comparison with `True` must make cases 2, 4 and 7 fail. The PR description records that this was checked.

### 4.4 Kubernetes mapping (#1909), stated honestly

A SPIFFE-format SAN makes the **format** portable. It does not make the **granularity** portable. Istio's identity is the service account, and many pods may share one. The plan must not claim the check carries over unchanged.

At #1909, choose one of these:

| Option | Broker-facing principal | Replay between sandboxes | Cost |
|---|---|---|---|
| **K1. Node forwarder (default proposal)** | A DaemonSet Envoy per node, with a per-node SVID, `spiffe://syntropic137/node/<node>` (SPIRE `k8s_psat` node attestation, or a cert-manager-issued certificate). The grant binds to the node the pod was scheduled on | Possible between pods on the same node, exactly as between workspaces on the same box today. Not possible off the node | The same check as today, with `box` renamed `node`. One SVID per node |
| **K2. Per-pod workload identity** | SPIRE with a pod-UID selector, issuing `spiffe://syntropic137/ns/<ns>/pod/<uid>`, or a per-execution service account under Istio | Not possible between pods | SPIRE server and agents, or service-account churn at 1,000 executions. **[U]** the Istio SVID issuance rate at that churn |
| **K3. Shared service-account mTLS (Istio STRICT)** | `spiffe://<td>/ns/<ns>/sa/<sa>` | **Possible between every pod sharing the service account.** Box binding is lost; only the capability remains | Lowest. Rejected as a binding, though acceptable as transport encryption |

On Kubernetes:

- Istio sidecars terminate mTLS before the application. The identity handoff in §4.3 therefore moves to whatever terminates TLS in front of the injector. **[U]** whether Istio's default XFCC forwarding to the application is configured in a way that meets §4.3 step 2. It must be verified at #1909.
- The tailnet goes away.
- The per-request ext_authz check and the deny reasons stay.

---

## 5. Option comparison (for the "H4 recommendation" section)

| Option | Threat model | Operational cost | Kubernetes mapping | Verdict |
|---|---|---|---|---|
| **Tailnet only** (shared reachability) | Box identity is the WireGuard node key. Anything that can send on `tailscale0` inherits it, including a sandbox if G3 egress is wrong. Nothing binds a capability to a box, so a stolen capability replays from any node the policy admits | Lowest; already operated. The cold-DERP outage is measured (`docs/handoffs/20260903-queued_after-vps-restart.md:155-161`), and the first probes on a cold route fail (`docs/testing/release-validation.md:476-480`) | None. Discarded | Rejected: no binding |
| **Tailnet + reviewed policy + broker-side source-IP binding** (strongest tailnet-only form) | The tailnet policy is managed as code through GitOps ([Tailscale policy syntax](https://tailscale.com/docs/reference/syntax/policy-file), as cited by the review). The broker maps the source `100.x` address to a `box_id` in Redis and compares it with the grant. This binds a capability to a box | No CA. One Redis key per box. **Fragile:** the identity is a network address, and any proxy or NAT between the tailnet and the injector erases it. **[I]** Docker port publishing on the broker host may already present the bridge address rather than the `100.x` source; this needs a probe | None. Pod IPs are not identities | **Runner-up.** A valid cheaper choice if the owner prefers no CA. Loses to mTLS on address independence and Kubernetes continuity |
| **Tailnet + per-box mTLS** (recommended) | The broker verifies a cryptographic box identity, independent of the network path. It binds capability to box (§4.3). Off-box replay is closed. Same-box replay remains, and the per-workspace capability still limits it | A small CA: an offline root with manual issue, or `step-ca` (decision 3). Per-box issue and renewal on roughly a 90-day cycle. A 14-day expiry alert. One Redis key per box. One field on the grant. One comparison | K1 is direct: box becomes node. K2 is a stronger upgrade. K3 is not a binding (§4.4) | **Recommended** |
| **SPIFFE/SPIRE workload identity now** | The strongest: attested, short-lived, rotated SVIDs, per workload if wanted | A SPIRE server with HA, plus an agent and attestation per box. Disproportionate for a handful of owned boxes. ADR-022 alternative 3 is "Partially adopted" for cloud deployments and lists homelab as a limitation (`docs/adrs/ADR-022-secure-token-architecture.md:308-315`), which agrees with not running it on owned boxes | Native (K1 or K2) | Adopted **in ID format only**. Running SPIRE is deferred to #1909 |
| **Cloudflare tunnel** (+ Access service token or client mTLS) | A third party terminates TLS on the path that carries model traffic and the account-wide OAuth bearers just allowed. The sandbox or box egress allow-list must include a public hostname | The pattern exists: `docker/docker-compose.cloudflare.yaml:17-34` targets `gateway:8081`. **[U]** whether a 300 s SSE stream survives the tunnel | Weak. A cluster uses its own ingress | Rejected for the broker. It remains the UI/API ingress |
| **Per-execution mTLS** (existing Rejected #4) | A certificate per sandbox | CRL/OCSP cannot meet 60 s, and harness CLIs do not reliably present client certificates | – | Still rejected. Per-box certificates checked against a Redis allow-list need no CRL or OCSP, so they do not reopen it |

## 6. Primary-source survey (carried from research; directionality made explicit)

These sources were read by the research phase at these commits: OpenHands software-agent-sdk `75105bd`, e2b-dev/infra `cfd393d`, daytonaio/daytona tag `v0.190.0`. Daytona's README on `main` says the project went private in June 2026.

| Platform | Hop the evidence covers | Mechanism | Where the upstream credential lives | Label |
|---|---|---|---|---|
| OpenHands Cloud / agent-server | **Sandbox → control plane** | A per-sandbox bearer, `X-Session-API-Key`. `get_llm()` fetches the raw key with `expose_secrets=true` | **In the sandbox** | [V] `openhands-workspace/openhands/workspace/cloud/workspace.py:220-265, 554-591`; `openhands-sdk/openhands/sdk/secret/secrets.py:113-130`. Private SaaS side: [U] |
| E2B | **Control plane → sandbox** (envd), the *opposite* direction | A per-sandbox `X-Access-Token`. Optional user SOCKS5 egress proxy with TLS to the proxy and no client certificate | The customer's choice; E2B has no broker | [V] `packages/orchestrator/pkg/sandbox/envd.go:266,496-497`; `packages/shared/pkg/sandbox-network/byop.go:78-95` |
| Modal | Sandbox egress → the platform's proxy | The egress proxy injects headers and terminates TLS with a per-sandbox CA. Identity is the sandbox's network position | **Outside the sandbox** (beta) | [V] https://modal.com/docs/guide/sandbox-secret-injection.md |
| Daytona (OSS) | **API → runner**, not sandbox → broker | A static per-runner bearer | The customer's choice | [V] `apps/runner/pkg/api/middlewares/auth.go:16-45`. Current private code: [U] |
| Kubernetes native | Workload → service | Audience-bound projected ServiceAccount token. Istio STRICT mTLS. SPIRE SVIDs | The control plane | [V] kubernetes.io projected volumes; Istio mTLS migration and egress-gateway docs. Istio itself says egress enforcement needs network policy below the proxy. SVID lifetimes: [U] |
| Tailscale | Node → node | WireGuard node key, tags and grants | – | [V] tailscale.com/kb/1068, /kb/1324. Ephemeral-node and auth-key wording: [U] |
| Cloudflare Access | Client → origin | A service token, or client mTLS | – | [V] developers.cloudflare.com service tokens and mTLS docs |

**What it supports.**

- Only OpenHands gives direct evidence about a sandbox authenticating to a credential holder, and it uses a bearer.
- The E2B and Daytona rows cover other hops. They show only that bearer tokens are common on those hops. They are **not** evidence of how sandboxes authenticate to brokers.
- Only Modal keeps the upstream credential out of the sandbox, as this plan's D1-D3 do.
- mTLS and SPIFFE appear at the node or workload-to-service layer. That is where §3 places them.

**Unconfirmed:**
- 300 s SSE through Cloudflare Tunnel
- the wording of Tailscale's ephemeral-node and auth-key semantics
- the private SaaS code of OpenHands Cloud and Daytona
- SPIRE SVID default lifetimes

---

## 7. Edit list for `docs/plans/20261014_credential-broker.md`

Before editing, find each location by its text. The line numbers are the review's, at `f5ddc382d`.

1. **Scope statement (≈14).** Replace the OAuth remote refusal with: Claude Max OAuth and Codex ChatGPT login are brokered on remote. Cite "owner decision 2026-10-14 (H1/H2)".
2. **D2 (grant record, ≈91).** Add `box_id` to the grant, sourced from the placement record (§4.3 step 6). Add the reserved value `local`.
3. **D3 (≈95-101).** Add OAuth residency, import, refresh ownership and persistence as in §4.1.2-4.1.4. Keep "upstream secrets only on the control plane" (≈95) and state that it now includes OAuth state.
4. **D4 table (≈114, 116).**
   - Claude OAuth/Max row: the broker holds the token, and the injection is `authorization: Bearer <oauth>`.
   - Codex ChatGPT row: the broker is the sole holder and refresher; the sandbox gets a capability-bearing auth file with no real tokens.
   - Both rows say "gated on S1 (a)-(c)".
5. **D5 (≈137-138).** Replace "Cloudflare tunnel or a tailnet (H4)" and "mTLS optional" with:
   - the two-hop topology of §4.2
   - a pointer to "H4 recommendation"
   - the statement that it applies to the central broker
   - the microVM-plan amendment sentence: the box Envoy is a secret-free forwarder and the injector runs on the control plane only
6. **D8 (≈203-205).** Delete the two refusal clauses. `BrokeredCredentials` refuses only for a class whose S1 gates failed.
7. **D10 (≈232) and the lifecycle (≈245).** Replace the class-selection rule with §4.1.1. Add OAuth upstream-state import and refresh beside the existing GitHub upstream-token installation and renewal.
8. **Grant check (≈263) and service interface (≈376).** Add the `box_id` comparison and the `peer: BrokerPeer` parameter (§4.3 step 5), with the three deny reasons.
9. **S1 (≈342).** Add gates (a), (b) and (c) from §4.1.5 as observable results. Keep the fallback sentence as the failure path. Mark them agentic-workspace work.
10. **PR 8 (≈497-503).** Respecify PR 8:
    - a remote listener with `require_client_certificate`, the box CA as its only trust root, and a SAN matcher
    - `SANITIZE_SET` with URI on that listener, plus `x-forwarded-client-cert` in the ext_authz `allowed_headers`
    - a per-listener ext_authz `path_prefix`
    - injector parsing and validation of XFCC
    - grant `box_id`
    - a Redis box allow-list
    - box Envoy forwarder config with a per-box client certificate and verification of the broker's server certificate
    - `SYN_BROKER_URL` as a tailnet address
    - an internal-only injector network

    Delete "tunnel route". Replace the happy-path test at ≈503 with the 7 acceptance cases and the mutation requirement from §4.3.

    Name the implementation surface:
    - `docker/sidecar-proxy/envoy.yaml:74-78` and `:250-269`
    - `docker/token-injector/token_injector.py:151`
    - `packages/syn-adapters/src/syn_adapters/workspace_backends/service/workspace_service.py:266`
    - the compose overlays under `docker/`
11. **OAuth implementation PR(s).** Add a PR, or extend the PR that owns the injector, for §4.1:
    - the `upstream_oauth_state` record and its encryption
    - seed import
    - single-flight refresh under the Redis lock
    - the deny reasons `upstream_oauth_refresh_failed` and `upstream_oauth_expired`

    It depends on S1 (a)-(c).
12. **Rejected alternatives (≈548).**
    - Keep #4, and add the sentence that per-box certificates do not reopen it.
    - Add the four non-recommended rows of §5: tailnet only, tailnet with source-IP binding (marked runner-up), SPIRE now, and Cloudflare tunnel.
13. **§7 Risks (≈556-570).** Add the rows from §8 of this document. Rewrite the exfiltrated-capability row (≈567) so its mitigation names the box-binding check, and add the same-box limitation.
14. **New section "H4 recommendation".** Contents:
    - the approval paragraph from §3
    - §3.1 and §3.2
    - the comparison from §5
    - the survey from §6, with its labels and commits
    - the Kubernetes mapping from §4.4
    - the "Unconfirmed" list
15. **§9 (≈598), §11 (≈614-618), review disposition (≈640), Readiness (≈644).**
    - H1 and H2: "DECIDED: ALLOW (owner, 2026-10-14). The terms-of-service consideration is the owner's accepted decision." Write no further ToS prose.
    - H4: "Recommended; awaiting one-line approval."
    - H5: the recommendation assumes central; choosing per-box reopens H4.
    - Readiness: no longer blocked on H1/H2. PR 8 is blocked on H4 approval. The OAuth classes are blocked on S1 (a)-(c).
16. **Follow-ups.** List these with full paths. Write "needs an issue" unless an issue number is known, and never invent one:
    - `docs/adrs/ADR-024-setup-phase-secrets.md:531`
    - `packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/handlers/WorkspaceProvisionHandler.py:271`
    - an ADR recording the broker transport and identity decision once H4 is approved

    Do **not** list ADR-022 alternative 3 as something to supersede. It is "Partially adopted" (`docs/adrs/ADR-022-secure-token-architecture.md:312`), and this design agrees with it.
17. **Commit and push.** Use one commit, referencing PR #1874, touching only this file, pushed to `docs/runtime-research-20261012` before `$SYN_PHASE_DEADLINE`.

## 8. Risks (rows to add)

| Risk | What would show it broke | Response |
|---|---|---|
| S1 (a) or (b) fails: the harness does not send its OAuth slot to a custom base URL in a form the broker can replace | The S1 turn fails, or the broker sees no replaceable header | That class stays `HostCredentials`-only on remote. The owner is told the decision was made but cannot be implemented for that harness |
| S1 (c) fails: the harness insists on refreshing by itself | Turns fail after expiry. Egress denials to the auth host | The same fallback. Never put a real refresh token in the sandbox to make it pass |
| Codex refresh race (two holders of one account) | `refresh_token_reused`-type errors, or 401 after a refresh | Account exclusivity (decision 4). The single-flight lock. Alert without retry |
| A seed re-import revives a rotated-away refresh token | 401 after an injector restart | The durable record wins, the seed is ignored with a warning, and re-import is explicit only |
| OAuth concentration: account-wide subscription tokens sit in the control plane's Postgres and Redis instead of one workspace's environment |, | Accepted together with H1/H2 (owner, 2026-10-14). Encryption at rest. Only the injector reads them |
| ToS |, | The owner's accepted decision, 2026-10-14. Not re-argued |
| A box certificate expires | Handshake failures in the box Envoy's upstream stats | Expiry metric and alert at 14 days |
| `box_id`/SAN mismatch after a box is renamed or reprovisioned | 403 `box_mismatch` | Distinct deny reason. Re-enrol runbook |
| Forged identity header | Acceptance cases 4 and 5 | `SANITIZE_SET` overwrite, the listener path prefix, and the internal-only injector network |
| In-flight stream outlives revocation | A stream continues up to 300 s after an allow-list delete | The same bound as capability revocation today (`docker/sidecar-proxy/envoy.yaml:184`). Stated, not hidden |
| Tailnet cold path | First-request failures after idle | Connect retries with backoff and keepalive in the box Envoy's cluster |
| A sandbox reaches `tailscale0` directly | A G3 probe from a guest to a `100.x` address succeeds | It grants nothing without the box key, but it is still a G3 failure and must be fixed |
| Owner picks H5 = per-box |, | H4 reopens. Nothing in this design covers it |

## 9. Verification (edit phase)

Run all commands from `/workspace/repos/syntropic137` with `BASE=f5ddc382ddcda968f3cdcc777f183ba48449a388`.

1. **Diff scope:** `git diff --name-only $BASE..HEAD` prints exactly `docs/plans/20261014_credential-broker.md`. The base is immutable, so this check stays meaningful after the push.
2. **Refusal removed:** `git diff $BASE..HEAD` shows the D4 rows ≈114/116, the D8 clauses ≈203-205 and the §11 H1/H2 entries ≈614-615 *replaced*. The new text says ALLOW, and no other row still says "Refused on remote". As a supporting check, `grep -nE "Refused on remote until H1|until H1/H2|blocked on human decisions H1"` on the file returns nothing.
3. **Lifecycle complete:** read D3, D10 and S1 in the edited file. They must name the selection rule, residency, import, sole refresher and gate (c). This is a reviewer read, not a grep.
4. **Section approvable:** `grep -n "^#\+ H4 recommendation"` returns one line. The first paragraph begins "Approve:" and names the central-broker condition.
5. **Comparison complete:** the table has rows for tailnet only, tailnet with source binding, per-box mTLS, SPIFFE/SPIRE and Cloudflare tunnel. Each row has threat-model, cost and Kubernetes cells.
6. **Identity handoff testable:** PR 8 lists the 7 acceptance cases and the mutation requirement.
7. **Unknowns kept:** the survey keeps every [U] from §6. E2B and Daytona are labelled with their actual direction.
8. **ADR-022 characterized correctly:** the document says "Partially adopted", and nothing in it proposes superseding ADR-022.
9. **Pushed:** after `git push`, `git rev-parse HEAD` equals `git rev-parse origin/docs/runtime-research-20261012`. This must happen before `$SYN_PHASE_DEADLINE`.
10. **Optional:** `just preflight-agent`. Report a failure in a docs-only change as pre-existing; do not fix it here.

## 10. Out of scope and follow-ups

- **Out of scope:**
  - any source, config, ADR, compose or `.github/workflows/` change
  - running S1, or any agentic-workspace change
  - choosing CA software
  - designing per-box brokering
  - editing the microVM plan
  - filing issues
- **Follow-ups**, named in the document as "needs an issue":
  - the ADR-024 matrix row
  - the WorkspaceProvisionHandler comment
  - a broker transport ADR once H4 is approved

## 11. Needs a human decision

These go into the document. None of them blocks making the edit.

1. **H4:** approve the one-line recommendation in §3, or choose the runner-up (tailnet with source-IP binding).
2. **H5:** confirm the central broker. Per-box reopens H4.
3. **CA operation:** an offline root with manual per-box issue (proposed at today's box count), or `step-ca` with ACME renewal (better at 10 or more boxes).
4. **Codex account exclusivity:** a ChatGPT account brokered remotely is not logged in anywhere else that refreshes it.
5. **Follow-up issues:** whether to file them now.

## Review disposition

| finding | accepted / rejected | what changed |
|---|---|---|
| B1: the OAuth edit list misses class selection, import, refresh ownership and persistence | **accepted** | New §4.1: D10 selection by class plus `auth_kind` with the current precedence; residency in control-plane Postgres plus a Redis cache; seed import from `packages/syn-shared/src/syn_shared/settings/config.py:309`, with the durable record winning; a single-flight sole refresher under a Redis lock; distinct deny reasons; S1 gate (c) for expiry, concurrency and no token in the sandbox. Edit list items 2, 3, 7 and 11 cover D2, D3, D10, the lifecycle and a new PR. Verified the premise: the Codex credential today is a static setting copied into the sandbox (`packages/syn-adapters/src/syn_adapters/workspace_backends/service/setup_phase_secrets.py:208-213`, `:731-751`) |
| B2: H4 not shown to hold for both H5 topologies | **accepted** | Withdrew the H5-independence claim. The recommendation is now explicitly conditional on the central broker (§3.2), with a full path spec (§4.2): terminators, residency, authorization point, revocation, disconnection. Per-box is declared undesigned, and choosing it reopens H4. The microVM-plan amendment (secret-free box forwarder) is stated |
| B3: identity handoff and negative tests unspecified | **accepted** | Verified the premise: HTTP ext_authz forwards only `host`/`x-forwarded-host` (`docker/sidecar-proxy/envoy.yaml:253-262`), and the injector reads only Host (`docker/token-injector/token_injector.py:151-153`). §4.3 names the handoff: a per-listener `path_prefix`, an XFCC overwrite with `SANITIZE_SET`, an internal-only injector network, SAN regex and issuer validation, `BrokerPeer` on `authorize`, `box_id` from the placement record, broker server verification by the box. It adds 7 real-Envoy acceptance cases and a mutation requirement |
| I1: a SPIFFE-shaped string does not make Kubernetes a drop-in | **accepted** | §4.4 replaces the drop-in claim with three options (node forwarder, per-pod SPIRE, shared service account) and says for each whether replay between sandboxes stays possible. The shared service account is rejected as a binding. Istio's termination point moves the handoff, and its XFCC behaviour is marked [U] |
| I2: ADR-022 alternative 3 is "Partially adopted", not rejected | **accepted** | Verified at `docs/adrs/ADR-022-secure-token-architecture.md:312`. The characterization is corrected in §5, and the "supersede ADR-022" follow-up is removed (edit item 16, verification step 8) |
| I3: compare the strongest tailnet-only option | **accepted** | Added the "tailnet + reviewed policy (GitOps) + broker-side source-IP binding" row as the named runner-up. Dropped "ACL outside review" as a reason. mTLS is now justified on address independence and Kubernetes continuity, and has to pay for its CA on those grounds |
| I4: moving-branch diff, date grep, survey directionality | **accepted** | Verification uses the immutable `BASE=f5ddc382d` and semantic reads of D3, D4, D8, D10, §11 and Readiness instead of a date grep. The survey table gains a "hop the evidence covers" column, with E2B and Daytona labelled as other directions and their limits stated |
| Review limit: "the earlier plan's inability to read another branch is not a current blocker" | **partly rejected** | True for the reviewer, who had git. This phase was granted no git tool, so it again could not read the branch. All target-document line numbers are the review's at `f5ddc382d` and must be found by text. Every claim about this repository's code in this document was re-read on `main` in this phase |

## Readiness

Ready to implement. The document edit can be made, committed and pushed to PR #1874 now. Inside the document, PR 8 stays blocked on the owner's one-line H4 approval, which assumes H5 = central broker, and the OAuth classes stay blocked on S1 gates (a)-(c).

