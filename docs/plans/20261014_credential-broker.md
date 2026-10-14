# Plan (final): #1735, no live upstream credential inside a remote sandbox (Claude, Codex, GitHub)

This is the revise phase. No repository files were changed. I checked this plan against syntropic137 `main` @ `6b5b0abe6`, with `lib/agentic-workspace` pinned at `5c4e559`.

The brief names one deliverable, `docs/plans/20261014_credential-broker.md`. PR 1 below writes it, and this document is its content. It replaces the plan-phase draft, so a reader does not need the research, the draft plan or the review.

**Delivered scope, stated up front.** The design brokers four credential classes:

- the Claude **API key**
- the Codex **API-key mode**
- the GitHub installation token for **git**
- the GitHub installation token for **gh**

Claude OAuth/Max and Codex ChatGPT-login mode are **refused on remote backends** until a human decides H1 and H2. Until then, closing #1735 means closing it for the API-key classes. The OAuth gap stays open and is listed as an acceptance gap (§9), not hidden.

---

## 1. What the code does today (verified)

| Fact | Evidence |
|---|---|
| The agent env holds the real Claude credential. OAuth is preferred, the API key is the fallback | `packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/handlers/WorkspaceProvisionHandler.py:272-275` |
| The setup phase also receives both Claude credentials | `packages/syn-adapters/src/syn_adapters/workspace_backends/service/setup_phase.py:61-65` |
| Codex `auth.json` stays in `~/.codex` for the whole run. Only the staged copy is removed | `packages/syn-adapters/src/syn_adapters/workspace_backends/service/setup_phase_secrets.py:731-751` |
| The GitHub installation token sits in `~/.git-credentials` (per repo, `x-access-token:<token>@github.com`) and in gh's `hosts.yml` | `packages/syn-adapters/src/syn_adapters/workspace_backends/service/setup_phase_secrets.py:775-849` |
| The injector is keyed by host, holds one global Anthropic credential built at import, and **prefers the caller-supplied `x-forwarded-host`** | `docker/token-injector/token_injector.py:57-97`, `docker/token-injector/token_injector.py:151-171` |
| The injector passes GitHub hosts through and sends no credential for them | `docker/token-injector/token_injector.py:99-109` |
| Envoy sends only `host` and `x-forwarded-host` to the check. It is fail-closed, and it overwrites `x-api-key`, `authorization` and `x-syn-execution-id` upstream | `docker/sidecar-proxy/envoy.yaml:250-269` |
| The access log's `execution_id` is an agent-controlled request header | `docker/sidecar-proxy/envoy.yaml:99` |
| There is one plaintext listener on 8081. Upstream TLS only | `docker/sidecar-proxy/envoy.yaml:74-78`, `docker/sidecar-proxy/envoy.yaml:322-330` |
| Model routes allow 300 s streams. git allows 120 s | `docker/sidecar-proxy/envoy.yaml:184`, `docker/sidecar-proxy/envoy.yaml:225` |
| `configure_tokens` and `stop` are Phase-1 no-ops. Every workspace gets the same handle id, `shared-envoy-proxy` | `packages/syn-adapters/src/syn_adapters/workspace_backends/docker/shared_envoy_adapter.py:75-100` |
| The proxy URL is a hard-coded default read from env | `packages/syn-adapters/src/syn_adapters/workspace_backends/service/workspace_service.py:267` |
| **A token-vending path is wired but inert.** `create_workspace` vends an `ANTHROPIC` token only, with a 300 s default TTL, and hands it to the no-op. `ManagedWorkspace.inject_tokens` discards the value | `packages/syn-adapters/src/syn_adapters/workspace_backends/service/workspace_service.py:517-519`, `packages/syn-adapters/src/syn_adapters/workspace_backends/service/workspace_service.py:112`, `packages/syn-adapters/src/syn_adapters/workspace_backends/service/managed_workspace.py:205-234` |
| The vending port takes `execution_id` only. No workspace id, no deadline. Revocation is per execution | `packages/syn-domain/src/syn_domain/contexts/orchestration/_shared/ports.py:127-140`, `packages/syn-adapters/src/syn_adapters/workspace_backends/service/workspace_lifecycle.py:249-254` |
| The injection adapter ignores the isolation handle and returns only a `TokenInjectionResult` | `packages/syn-adapters/src/syn_adapters/workspace_backends/tokens/token_injection_adapter.py:81-137` |
| `TokenType` has a single `GITHUB` member | `packages/syn-domain/src/syn_domain/contexts/orchestration/domain/aggregate_workspace/value_objects.py:61-67` |
| The ADR-072 platform token is the precedent for a hashed, deadline-bounded bearer. Its `bound_to_deadline` is **read-then-write**, not atomic | `packages/syn-adapters/src/syn_adapters/platform_access/__init__.py:184-245`; read at `:216`, write at `:224` |
| The platform grant's deadline is learnt at launch, in `stream()` | `packages/syn-adapters/src/syn_adapters/workspace_backends/service/managed_workspace.py:174-195` |
| Hardened host-initiated git runs with `HOME=/nonexistent` and gets back only a **fixed** set of github.com settings | `packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/workspace_git.py:174-207` |
| gh holds **one** token, routed to the first repo under work. Repo-less workflows mint a token that is not repo-scoped. `GH_REPO` is `owner/repo` with no host | `packages/syn-adapters/src/syn_adapters/workspace_backends/service/setup_phase_secrets.py:323-363`, `packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/handlers/WorkspaceProvisionHandler.py:314-342` |
| GitHub minting is owned by `SetupPhaseSecrets.create` and the issuance ledger. Renewal re-mints and execs a script into the container | `packages/syn-adapters/src/syn_adapters/workspace_backends/service/git_credential_renewal.py:110-155` |
| Teardown revokes GitHub tokens upstream after the unpushed-work guard | `packages/syn-adapters/src/syn_adapters/workspace_backends/service/workspace_service.py:532-537`, `packages/syn-adapters/src/syn_adapters/workspace_backends/service/managed_workspace.py:331-352` |
| The salvage push is bounded at 20 s. The interrupt budget is 60 s | `packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/workspace_git.py:102`, `packages/syn-shared/src/syn_shared/settings/execution.py:26-33` |
| ADR-024 records direct OAuth injection as accepted posture | `docs/adrs/ADR-024-setup-phase-secrets.md:525-534` |
| E2B Decision 6 sketches a broker, with egress limited to "the broker, github.com and the package registries" | `docs/research/2026-10-08-remote-executor-e2b.md:361-378` |

Two documents are on `origin/docs/runtime-research-20261012` only, not on `main`:

- `docs/plans/20261013_selfhosted-microvm-pool.md` (the G3 credential gate)
- `docs/research/2026-10-14-openhands-workspace-abstraction.md` (OpenHands puts plaintext secrets in the sandbox; this plan is the opposite)

They are cited by ref, without line numbers.

Today a canary scan of any running workspace would find all three classes.

## 2. Pass bar (#1735)

The bar, as the brief states it:

1. A canary scan at every phase boundary finds zero live upstream credentials.
2. Model calls, `git push` and `gh` succeed through an off-host broker.
3. Revoking a workspace at the broker stops its access within 60 s.

The review reports that the issue also asks for a full `sdlc-implement-v3` run on a non-local backend, with argv coverage and planted positive canaries. I could not read the issue in this phase: I had no network tool. Those requirements are stricter, so §8 adopts them either way.

---

## 3. Decisions

### D1. The broker is the existing Envoy and token-injector, made grant-keyed. No new service.

Envoy keeps the jobs it already does well:

- routing
- upstream TLS
- fail-closed ext_authz
- header overwrite

The injector stops asking "which host is this?". It answers "**which grant is presenting, and may it reach this route?**". The method-agnostic dispatch stays as it is (`docker/token-injector/token_injector.py:124-149`).

### D2. The sandbox holds only per-workspace, per-class capabilities.

- **Classes.** Reuse `TokenType` (`packages/syn-domain/src/syn_domain/contexts/orchestration/domain/aggregate_workspace/value_objects.py:61-67`).
  - `ANTHROPIC` and `OPENAI` are kept.
  - Add `GITHUB_GIT = "github_git"` and `GITHUB_API = "github_api"`.
  - Keep `GITHUB` only so old `TokensInjectedEvent`s still replay. Nothing new issues it.
  - The split means a stolen model capability cannot push, and a stolen git capability cannot call the REST API.
- **The capability.** It is 32 bytes of host-generated entropy. Its **wire form** is decided by the presenter (D6).
- **The grant.** The broker stores only `sha256(wire form)`, with:
  - `execution_id`, `workspace_id`, `token_type`, `expires_at`
  - for GitHub classes, the upstream token(s) (D3)
- **Lookup.** The broker reads Redis on every check and keeps no positive cache (Rejected #8).

### D3. Upstream credentials live only on the control plane.

**Anthropic and OpenAI API keys** stay in the injector's environment, as today.

**GitHub tokens:**

- They are still minted by `SetupPhaseSecrets.create` and recorded in the issuance ledger. That path stays the **only** minting owner (`packages/syn-adapters/src/syn_adapters/workspace_backends/service/git_credential_renewal.py:110-120`).
- In brokered mode only the **destination** changes. Instead of a script exec'd into the container (`packages/syn-adapters/src/syn_adapters/workspace_backends/service/git_credential_renewal.py:136-148`), the minted tokens are written into the grants:
  - `GITHUB_GIT`: a map of `owner/repo` → token
  - `GITHUB_API`: exactly one token, the one `_gh_token_for_repo_under_work` or `_mint_repo_less_gh_token` already selects (`packages/syn-adapters/src/syn_adapters/workspace_backends/service/setup_phase_secrets.py:323-363`)
- Because GraphQL needs one token rather than a repo lookup, the broker parses no GraphQL. Cross-installation gh stays out of scope, as it is today.

`credential_keeper` keeps its 40-minute schedule. Upstream revocation at teardown (`packages/syn-adapters/src/syn_adapters/workspace_backends/service/managed_workspace.py:331-352`) also stays, as defence in depth.

### D4. What the harness sees.

| Class | In the sandbox | Broker route | Added by the broker | Removed by the broker |
|---|---|---|---|---|
| Claude API key | `ANTHROPIC_BASE_URL=<broker>/anthropic` and the wire capability, in the form S1 finds the pinned CLI accepts | `/anthropic/*` → `api.anthropic.com` | `x-api-key: <real>` | `authorization` (if that carried the capability) |
| Claude OAuth/Max | **nothing**. Refused on remote until H1 | – | – | – |
| Codex API-key mode | provider base URL `<broker>/openai` and the wire capability (S1) | `/openai/*` → `api.openai.com` (new route and cluster: Codex has no proxy path today) | `authorization: Bearer <real>` | `x-api-key` if present |
| Codex ChatGPT mode | **nothing**. Refused on remote until H2 | – | – | – |
| git | `~/.git-credentials` entries `<scheme>://x-access-token:<cap>@<git-authority>/<owner>/<repo>[.git]`, plus `url.<git-authority>/.insteadOf` for each of `https://github.com/`, `git@github.com:` and `ssh://git@github.com/` (see D9), and `credential.<git-authority>.useHttpPath=true` | git authority → `github.com` | `authorization: Basic base64(x-access-token:<real token for that owner/repo>)` | – (overwritten) |
| gh | Per S2. Primary: gh enterprise-host mode, with `hosts.yml` keyed to the GitHub authority, `oauth_token: <cap>`, and `GH_HOST`/`GH_REPO` qualified with that host. Fallback: `HTTPS_PROXY` plus a broker CA | GitHub authority, `/api/v3/*` → `api.github.com/*`, `/api/graphql` → `/graphql` | `authorization: token <real gh token>` | – (overwritten) |

**git's challenge.** git sends credentials only after a `401` with `WWW-Authenticate: Basic`. For the git class, the injector therefore answers a request **with no capability** with `401` and that header, not `403`. A wrong, expired or revoked capability gets `403`.

**One owner for git/gh presentation.** All of it lives in one new syntropic137 module, `syn_adapters.workspace_backends.service.github_presentation`, extracted from `setup_phase_secrets`:

- the credential-store lines
- `hosts.yml`
- `GH_HOST` / `GH_REPO`
- the insteadOf settings
- the settings handed to hardened git (D9)

git and gh speak GitHub's protocol, not a model harness's. Their configuration is generated here today and is pinned to `workspace_git` by a test. Moving half of it to agentic-workspace would split one contract across a release boundary. H10 asks the owner to confirm this reading of the CLAUDE.md boundary.

**gh's layout.** gh parses `owner/repo` from remotes and, in enterprise mode, wants `/api/v3` at the root. So GitHub gets a **dedicated broker authority**: a hostname remotely, a Docker network alias locally. Model providers use path prefixes on the main authority.

### D5. Network path. One code path; only the URL differs.

- **Local.** `http://envoy-proxy:8081` on `agent-net`. The workspace still presents a capability: there is no "local is trusted" branch once the legacy entry is gone (PR 7).
- **Remote.** A new TLS listener with its server certificate from settings, reached through an authenticated public ingress (the Cloudflare tunnel pattern, `docker/docker-compose.cloudflare.yaml`) or a tailnet (H4). The listener is enabled only by PR 8, which lands **after** PR 7 has deleted the legacy host-keyed path. A remote caller can therefore never reach a route that injects without a grant.
- **Authentication.** The capability authenticates the workspace. Box-level mTLS or a source allowlist is optional defence in depth (H4).
- **Remote egress** is deny-all, except the broker authorities and the package registries.
  - **This is a deliberate change from E2B Decision 6**, which also allowed github.com (`docs/research/2026-10-08-remote-executor-e2b.md:363-366`).
  - With git and gh brokered, direct github.com only adds an exfiltration channel and a path around audit.
  - Anonymous public reads go through the broker's GitHub routes.
  - H4 confirms.

### D6. Harness presentation lives in agentic-workspace, behind a Protocol defined here.

syntropic137 defines one Protocol in `packages/syn-domain/src/syn_domain/contexts/orchestration/_shared/ports.py`:

```python
class HarnessCredentialPresenter(Protocol):
    token_type: TokenType
    def wire_credential(self, entropy: SecretStr) -> SecretStr: ...
    def present(self, wire: SecretStr, base_url: str) -> PresentedCredentials: ...
```

`PresentedCredentials` is a frozen Pydantic model of `env: Mapping[str, SecretStr]` and `files: tuple[PresentedFile, ...]`.

**The hash contract.** This resolves the conflict the review found (B3):

1. The **host** generates the entropy.
2. It calls the presenter's `wire_credential` **before** registering anything.
3. It stores `sha256(wire)`.
4. It hands `wire` to `present`.

The presenter may wrap the entropy however the CLI's local check needs, for example a well-formed `sk-ant-…` value per #724. The broker extracts the credential from the **standard HTTP auth scheme** and hashes it:

- `x-api-key` value
- `Bearer` / `token` parameter
- Basic **password**

The broker has no CLI-specific unwrapping. The presenter has no knowledge of the broker's store.

**Implementations.**

- `agentic_isolation.harnesses.{claude,codex}.credentials` implement the Protocol.
- The GitHub presenters (D4) are identity encoders here.
- syntropic137 never spells a harness env-var name, a placeholder format or a Codex config key.

The APSS `CredentialBinding` (AW `914129d`) is usable unchanged: what it binds is the wire capability, never the upstream credential. Using it needs the submodule bump that remote providers need anyway.

### D7. Audit is Lane 2.

The injector emits one structured line per check, **including denials**, with these fields:

- `ts`, `execution_id`, `workspace_id`, `token_type`
- `repo` (git)
- `route`, `decision`, `reason`
- `x-request-id`

It never logs the capability, its hash or any upstream value.

**Trusted attribution in Envoy's access log.** The injector returns `x-syn-audit-execution-id` and `x-syn-audit-workspace-id` on the allow response. Envoy is configured with `authorization_response.dynamic_metadata_from_headers` for those two names. The access log reads `%DYNAMIC_METADATA(envoy.filters.http.ext_authz:x-syn-audit-execution-id)%` instead of the agent-controlled `%REQ(X-Syn-EXECUTION-ID)%` (`docker/sidecar-proxy/envoy.yaml:99`). `x-syn-execution-id` comes off `allowed_upstream_headers` (`docker/sidecar-proxy/envoy.yaml:268`); the audit headers are never on that list.

**Lane 1.** Grant issue stays the existing `TokensInjectedEvent`, which records types only and never values. Revocation and expiry are infrastructure state bounded by the deadline, not events. That matches the crash model in `packages/syn-adapters/src/syn_adapters/workspace_backends/service/credential_keeper.py:18-23`: after a crash the container is gone, and the grant dies at its deadline.

### D8. One switch: `WorkspaceCredentialPolicy`.

This follows E2B Decisions 5 and 6 (`docs/research/2026-10-08-remote-executor-e2b.md:312-378`).

- There are two implementations, `HostCredentials` (today) and `BrokeredCredentials`.
- The backend kit fixes the policy at wiring. It is never chosen per run.
- Every credential source consults it.
- `BrokeredCredentials` refuses before `create_workspace` when:
  - the only Claude credential is OAuth (H1)
  - Codex is in ChatGPT mode (H2)

### D9. Hardened host-side git keeps working.

Today `PROVISIONED_REMOTE_SETTINGS` is a fixed tuple of github.com settings (`packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/workspace_git.py:194-198`). A hardened command with no HOME would lose a global insteadOf to the broker, and then find no matching credential.

**Change.** Replace the tuple with `provisioned_remote_settings(git_authority: str | None)`.

- With `None`, it returns today's three settings unchanged.
- With an authority, it returns:
  - `credential.<authority>.useHttpPath=true`
  - `url.<authority>/.insteadOf=https://github.com/`
  - `url.<authority>/.insteadOf=git@github.com:`
  - `url.<authority>/.insteadOf=ssh://git@github.com/`

**Why the SSH rewrites point straight at the broker:** git applies a single insteadOf, so it does not chain an SSH rewrite through `https://github.com/`.

**Where the authority comes from.** It comes from the host's own `BrokerGrantSet` on `ManagedWorkspace`, never from the sandbox's config. Nothing else of the sandbox's global config is restored, so the #1815 hardening is preserved. `github_presentation` writes the same settings into the setup script, and the existing pin test now pins both shapes.

**Revocation timing.** Git grants are bounded to `deadline + interrupt_budget_s` (60 s, `packages/syn-shared/src/syn_shared/settings/execution.py:26-33`), not to the bare deadline. A salvage push after a deadline kill must still authorize. Model and gh grants are bounded to the deadline.

### D10. The grant lifecycle, end to end. One issuer.

This is the call chain the review found missing (B1).

1. **Class selection, in the handler.** `WorkspaceCredentialPolicy.request_for(phase, repos)` returns a frozen `CredentialRequest`. It holds `entries: tuple[CredentialRequestEntry, ...]`, each a `token_type` and a presenter.
   - `ANTHROPIC` if a Claude agent may run (`_agents_that_may_run`)
   - `OPENAI` if a Codex agent may run in API-key mode
   - `GITHUB_GIT` if `repos` is non-empty, **including `clone_repos: false`**, whose setup still writes credentials
   - `GITHUB_API` whenever gh will be given a token, which includes repo-less workflows

   `HostCredentials` returns today's `[ANTHROPIC]` request, still inert.
2. **Issue, at workspace creation.** `create_workspace(..., credential_request=...)` replaces the `inject_tokens` / `token_types` pair (`packages/syn-adapters/src/syn_adapters/workspace_backends/service/workspace_service.py:517-519`). The call goes `ManagedWorkspace.inject_tokens(request)` → `SidecarTokenInjectionAdapter.inject(workspace_id=, execution_id=, request=, ttl_seconds=)` → `TokenVendingPort.vend_token(token_type, execution_id, *, workspace_id, encoder, ttl_seconds)` → `BrokerGrantService.issue`.
   - **This is the only issuer.**
   - `SidecarPort.configure_tokens` stays a documented no-op for the shared broker: the grant store *is* the configuration, and a handle id shared by every workspace carries no identity.
3. **The return channel.** `inject` returns `InjectedCredentials(result: TokenInjectionResult, grants: BrokerGrantSet)`.
   - `BrokerGrantSet` (frozen, `repr=False` on values) holds `workspace_id`, `model_base_url`, `git_authority`, `github_authority`, and one `IssuedCapability(token_type, wire: SecretStr, expires_at)` per class.
   - `ManagedWorkspace` keeps it as `broker_grants`, beside `platform_grant`.
   - `TokenInjectionResult`, which reaches the aggregate, gains nothing secret.
4. **Initial expiry.** A new setting, `SYN_BROKER_GRANT_MAX_TTL_S`, defaults to the longest permitted phase timeout plus the interrupt budget. It replaces the 300 s `default_token_ttl` for brokered grants (`packages/syn-adapters/src/syn_adapters/workspace_backends/service/workspace_service.py:112`). A 300 s grant would die during setup.
5. **Upstream at setup.** `SetupPhaseSecrets.create` mints exactly as today. Under `BrokeredCredentials`, `github_presentation` writes capability-bearing files, and the minted tokens go to `BrokerGrantService.set_upstream` (D3). Renewal does the same through the same call, instead of `_install`.
6. **Launch.**
   - `_build_agent_env` merges `presenter.present(grants.wire(t), grants.model_base_url)` for the model class. It no longer reads `settings.claude_code_oauth_token` / `anthropic_api_key` under `BrokeredCredentials`.
   - `ManagedWorkspace.stream()` bounds every grant to its deadline, exactly where it already bounds the platform grant (`packages/syn-adapters/src/syn_adapters/workspace_backends/service/managed_workspace.py:174-195`). Git grants get the D9 grace.
7. **Teardown.** In `create_workspace`'s `finally`, after the guard and beside `_revoke_platform_grant` (`packages/syn-adapters/src/syn_adapters/workspace_backends/service/workspace_service.py:532-537`), call `BrokerGrantService.revoke_workspace(workspace_id)`.
   - `TokenVendingPort.revoke_tokens(execution_id)` becomes `revoke_workspace(workspace_id)` (`packages/syn-domain/src/syn_domain/contexts/orchestration/_shared/ports.py:138-140`).
   - The execution-keyed `_revoke_tokens` in `packages/syn-adapters/src/syn_adapters/workspace_backends/service/workspace_lifecycle.py:249-254` follows.

### D11. Atomic grant store. Revocation cannot be undone by a late writer.

The platform precedent reads and then writes (`packages/syn-adapters/src/syn_adapters/platform_access/__init__.py:216-224`). Copied as is, a renewal or deadline bound racing a revoke would resurrect the grant. The broker store differs in five ways:

- **Layout.** Each grant is a Redis hash at `syn:broker-grant:<sha256>`. Its TTL is authoritative. A set `syn:broker-ws:<workspace_id>` indexes it.
- **`set_upstream`** is a Lua script that does `if EXISTS then HSET upstream … end`. HSET keeps the key's TTL, and a missing key stays missing.
- **`bound_to_deadline`** is a Lua script that does `if EXISTS and PEXPIRETIME > target then PEXPIREAT target; HSET expires_at end`. It never extends.
- **`revoke_workspace`** is a Lua script that does `SMEMBERS index → DEL each member → DEL index`, in one atomic step.
- **Issue** writes the grant and its index entry in one `MULTI`. The index's TTL is at least the longest grant's.

The injector checks `EXISTS` plus `expires_at` on every request. A revoked grant is therefore denied on the next request, which in practice is about 1 s later.

### D12. A constructive guarantee, then a scan as evidence.

The scan in a remote sandbox runs inside something we do not trust. So the primary guarantee is constructive: **no upstream secret is ever sent into the sandbox.**

Under `BrokeredCredentials`, `ManagedWorkspace` puts a `SendGuard` at the three host→sandbox choke points:

- `execute` / `stream` environment
- `inject_files` / `copy_to`
- setup and renewal script text

The guard refuses any payload containing a configured upstream secret, in any of the D13 encodings. The scan (D13) is then independent evidence against accidental placement and harness side-channels, with its limits stated.

### D13. The canary scanner, specified as a detector.

`packages/syn-adapters/src/syn_adapters/workspace_backends/service/credential_canary.py` provides `scan(workspace, secrets) -> CanaryReport`.

**Coverage**

- `/proc/[0-9]*/environ` **and** `/proc/[0-9]*/cmdline`, for every process. The scan runs as root in the container.
- Every regular file on every **writable** mount in `/proc/mounts`, excluding `/proc`, `/sys` and `/dev`. Walked with `find -xdev` per mount.

**Transport and matching**

- Content is streamed **out** and matched **host-side**. A canary is never sent in to `grep` for: that would place it.
- Files above a per-file cap (default 16 MiB) are not partly read. They are reported as gaps.

**Encodings matched for each secret**

- raw
- URL-encoded
- base64 of the secret, at all three byte alignments
- base64 of `x-access-token:<secret>`, at three alignments (the Basic auth form, from `packages/syn-adapters/src/syn_adapters/workspace_backends/service/setup_phase_secrets.py:843-849`)

**Result**

`CanaryReport(status: clean | found | incomplete, findings: tuple[Finding(location, encoding, secret_label)], gaps: tuple[Gap(location, reason)])`. The secret value never appears in a report.

**Gaps** make the status `incomplete`:

- exec failure
- a file or process that is unreadable for permissions
- an oversize file
- a mount the walk could not finish

A pid that vanishes mid-scan is recorded as `vanished` and is not a gap: a process that has exited holds nothing.

**Boundaries.** It runs under `SYN_CREDENTIAL_CANARY=off|report|enforce` at three points:

- after setup, before agent launch
- after agent exit, before the guard
- after the guard, before teardown

**`enforce` outcomes**

- **Pre-launch, `found` or `incomplete`:** the phase fails before the agent starts, and grants and GitHub tokens are revoked. This is **fail-closed on incomplete.**
- **Post-exit, `found`:** the phase fails with a distinct `credential_canary_hit` reason. GitHub tokens are revoked upstream immediately, and a Lane 2 alert names the class so an operator rotates the API key. Pushed work stays as is, because a push cannot be undone.
- **Post-exit, `incomplete`:** the phase is recorded with a `canary_incomplete` warning and is not failed. The agent already ran, so failing gains nothing.

**Stated limits** (written into the report's docstring and into ADR-076):

- A hostile agent with root in the sandbox can hide from an in-sandbox exec.
- Compressed content, such as git packs and archives, is not decoded.
- Memory that is in neither environ nor argv is not read.

The scan is evidence, not attestation. The guarantee is D12.

---

## 4. Ordered PRs, with exit tests

The spikes S1 and S2 run in parallel with PRs 1-4.

### S1 (agentic-workspace), harness presentation and wire round trip

- For each pinned CLI (Claude, Codex API-key mode), find a `wire_credential` / `present` pair that passes the CLI's local checks and sends the capability to `<base_url>/…`.
- Record the result in an AW decision doc.
- *Exit:* an in-image test runs the pinned CLI against a fake upstream. It asserts one request at `/anthropic/v1/messages` (or `/openai/…`) whose standard auth value hashes to `sha256(wire_credential(entropy))`, and that **no** other credential is present.
- If no presentation passes for a class, that class stays `HostCredentials`-only and remote refuses it. PR 1 records the outcome.

### S2 (syntropic137), git and gh through the broker

Run the image's real `git` and `gh` against Envoy configured per D4 and a fake GitHub. The matrix:

- clone, fetch and push to a github.com origin, via insteadOf
- the 401 challenge path
- submodule URLs with and without `.git`
- `GH_REPO`-provisioned `gh pr create` with `clone_repos: false` (no git tree)
- a repo-less workflow (`gh issue list -R owner/repo`)
- an explicit `https://github.com/...` URL argument
- `gh api graphql`
- `gh api repos/...`

*Exit:* every case reaches the fake GitHub with the right real token, and the sandbox's files contain only capabilities. Choose primary or fallback for gh. If enterprise mode needs `GH_REPO=<host>/owner/repo`, that is settled here and implemented in `github_presentation`.

### PR 1 (syntropic137, docs)

- `docs/plans/20261014_credential-broker.md`: this plan.
- `docs/adrs/ADR-076-credential-broker.md`:
  - amends ADR-022 and the ADR-024 matrix (`docs/adrs/ADR-024-setup-phase-secrets.md:525-534`)
  - records H1-H10 and the D13 limits
- Retarget `TODO(#725)` at `docker/token-injector/token_injector.py:20-21` and `packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/handlers/WorkspaceProvisionHandler.py:289-290` to #1735.
- Fix `infra/docs/github-app-security.md:211`.
- Add **capability**, **grant**, **wire credential** and **broker** to `docs/architecture/orchestration-ubiquitous-language.md`.
- *Exit:* `just preflight-agent`. The ubiquitous-language fitness test fails if a term is missing.

### PR 2 (syntropic137), `syn_tokens.broker` grant store (D2, D11)

- `BrokerGrant`: frozen Pydantic with `extra="forbid"`. It holds `upstream: dict[str, SecretStr]`, a typed value map.
- The `BrokerGrantStore` Protocol, with two implementations:
  - `RedisBrokerGrantStore`, using the Lua scripts in D11
  - `InMemoryBrokerGrantStore(InMemoryAdapter)`
- `BrokerGrantService` with `issue`, `set_upstream`, `bound_to_deadline`, `revoke_workspace` and `authorize(presented, token_type, route) -> BrokerGrant | Denial`.
- It is its own module. There is no shared token framework with `platform_access`: their authorization decisions differ (`packages/syn-adapters/src/syn_adapters/platform_access/__init__.py:231-245`).
- *Exit tests.* (a)-(e) are unit tests; (f) uses Redis via the test-stack/testcontainers fixture.
  - (a) After `issue`, no Redis key or value contains the wire value.
  - (b) `revoke_workspace(A)` leaves workspace B of the same execution authorized.
  - (c) Expired, wrong-class and unknown capabilities give distinct `Denial`s.
  - (d) `bound_to_deadline` never extends.
  - (e) The in-memory store raises outside test/offline (ADR-060).
  - (f) **Deterministic interleavings against real Redis:** read → `revoke_workspace` → `set_upstream`, and the same for `bound_to_deadline`. Each leaves no key and `authorize` denies.
- Reverting to a read-then-write fails (f). Reverting to plaintext keys fails (a).

### PR 3 (syntropic137), the seam (D10). Inert until PR 4.

- Add `TokenType.GITHUB_GIT` and `GITHUB_API`.
- Add `CredentialRequest`, `HarnessCredentialPresenter`, `PresentedCredentials`.
- Change the port signatures: `vend_token(..., workspace_id, encoder, ...)` and `revoke_workspace`.
- `InjectedCredentials` and `BrokerGrantSet` on `ManagedWorkspace`.
- `SYN_BROKER_GRANT_MAX_TTL_S`.
- Deadline bounding in `stream()`.
- Revoke in the `create_workspace` `finally`.
- Renewal writes to grants in brokered mode.
- `health_check` gets an explicit admin-URL setting instead of `replace(':8081', ':9901')` (`packages/syn-adapters/src/syn_adapters/workspace_backends/docker/shared_envoy_adapter.py:108`).
- *Exit test (unit):* a provisioning test through `WorkspaceService.create_workspace` with the in-memory store, a fake isolation provider and presenter doubles. **Two workspaces of one execution**, all four classes requested. It asserts:
  - each presenter received a wire value that `authorize` accepts for its class only
  - the GitHub grants carry the minted upstream after setup
  - a renewal changes `upstream` and not the capability
  - grants still authorize during the unpushed-work guard
  - after A's teardown, A is denied and B is not
  - `TokensInjectedEvent` carries no value

  A store-only test could not catch a missing delivery; this one does.

### PR 4 (syntropic137, infra), the injector reads grants

**`docker/token-injector/token_injector.py`:**

- `ThreadingHTTPServer`
- a Redis client (password from a Docker secret, on the `syn-internal` network)
- `authorize()` imported from `syn_tokens.broker`, which is installed into the image so reader and writer cannot drift
- the token type from one `UPSTREAM_ROUTES` table keyed on **(`:authority`, normalized path prefix)**
- **`x-forwarded-host` ignored**
- fail-closed on any Redis error
- the 401 challenge for git
- the D7 audit line and audit headers

**`docker/sidecar-proxy/envoy.yaml`:**

- Send `authorization` and `x-api-key` to the check. Stop sending `x-forwarded-host`.
- `normalize_path: true` and `merge_slashes: true` on the HCM, so router and injector see the same path.
- Broker routes, the GitHub and git authorities (S2 layout), and the `/openai` route and cluster.
- The injector returns `x-envoy-auth-headers-to-remove` for the capability-bearing header whenever it injects a different one.
- `dynamic_metadata_from_headers` and the access-log change (D7).
- Drop `x-syn-execution-id` from upstream headers.

**Coexistence with legacy.** The legacy host-keyed Anthropic entry (`docker/token-injector/token_injector.py:57-97`) answers **only** on the existing 8081 `agent-net` listener's legacy virtual host. The listener is infrastructure that no caller selects, and the legacy host is never a remote route. This is the same exposure as today, and PR 7 deletes it.

**Fitness.** `ci/fitness/infrastructure/test_proxy_hostname_agreement.py` becomes a route↔class agreement test. Every broker route in envoy.yaml must map to a row in `UPSTREAM_ROUTES`, and vice versa. `test_proxy_method_agreement.py` still holds.

*Exit tests:*

- `docker/token-injector/tests/test_token_injector.py`:
  - a capability gives 200 and the real header
  - revoked gives 403
  - Redis down gives 403
  - wrong class gives 403
  - no credential on the git route gives 401 with `WWW-Authenticate`
  - a **spoofed `x-forwarded-host`** does not change the class
  - a **wrong-authority** request with a valid capability for another class gives 403
  - when **both** `authorization` and `x-api-key` are present, only the class's header authorizes and the other is removed
  - the audit line contains neither the capability nor the upstream value, **including on denials**
- **A real-Envoy test** (compose test stack) asserts that the access-log record's `execution_id` comes from metadata even when the request sets `X-Syn-EXECUTION-ID: forged`, and that the fake upstream never receives the capability header.
- **A load test** of the check at the request rate of 1,000 concurrent workspaces, recording p99. It must be far below the 5 s check timeout (`docker/sidecar-proxy/envoy.yaml:257`). Raise the injector's container limits to the measured need.

### PR 5 (syntropic137), policy, GitHub presentation, hardened git, SendGuard

- `WorkspaceCredentialPolicy` (`HostCredentials` / `BrokeredCredentials`), consulted by:
  - `_build_agent_env` (`packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/handlers/WorkspaceProvisionHandler.py:236-291`)
  - `SetupPhaseSecrets` (`packages/syn-adapters/src/syn_adapters/workspace_backends/service/setup_phase_secrets.py:731-849`)
  - the setup env (`packages/syn-adapters/src/syn_adapters/workspace_backends/service/setup_phase.py:61-65`)
  - the refusal rules (D8)
- `github_presentation` (D4) and `provisioned_remote_settings` (D9).
- `SendGuard` (D12).
- The default stays `HostCredentials`.

*Exit tests:*

- **Unit, under `BrokeredCredentials`:**
  - the agent env, setup env, setup script, staged files and renewal script contain no configured canary in any D13 encoding
  - `SendGuard` refuses a planted one at each choke point
- **Unit, under `HostCredentials`:** output is byte-identical to today, pinned by the existing `test_setup_phase_secrets.py` expectations.
- **Integration (test stack):** an actual **quarantine push** through the hardened builder (`HOME=/nonexistent`) from a workspace whose origin is ordinary `https://github.com/owner/repo` and `git@github.com:owner/repo`. It goes through Envoy to the fake GitHub and arrives with the real token. Reverting D9 fails it. PR 3's "grant still authorizes" test would not.

### PR 6 (agentic-workspace), presenters from S1

- `agentic_isolation/harnesses/{claude,codex}/credentials.py` satisfy the Protocol structurally.
- This is Python only, with no image change. It needs a submodule bump here, not `release` → `PINNED_DIGESTS`. The exception is if S2 picks the gh CA fallback: that is an image change and pays the release cost.
- *Exit:* S1's tests become AW CI tests pinned to the CLI versions in the image manifest.
- **Plus a round-trip test in syntropic137,** after the bump: the **real** AW presenter → `BrokerGrantService.issue` → `present` → the injector's `authorize`, for each class. If S1 adopted a transformed wire form, the test includes it. Separate presenter and broker tests using different strings would both pass while the composition fails; this test cannot.

### PR 7 (syntropic137), scanner and the fake-upstream end-to-end test

- `credential_canary.py` per D13, wired at the three boundaries.
- *Exit tests, for the detector (unit and test stack):*
  - plant raw and each encoded canary in a sleeping process's env, in a process's argv, and in a file under each covered mount: each gives `found` with the right location
  - an oversize file gives `incomplete`
  - an unreadable file gives `incomplete`
  - an exec failure gives `incomplete`
  - a process that exits mid-scan gives `vanished` and stays `clean`
  - an empty sandbox gives `clean`

  A scanner that always returns `clean` fails the planted cases.
- *Exit tests, end to end on the test stack:*
  1. Envoy clusters point at a recording fake upstream for Anthropic, OpenAI and GitHub git/REST/GraphQL. Upstream secrets are fresh random canaries per test.
  2. Provision a brokered workspace through the production `WorkspaceProvisionHandler` path, not a hand-built workspace.
  3. Scan: `clean`.
  4. From inside the workspace: a model call via the presented base URL, `git clone` + `git push`, `gh api`, `gh api graphql`.
  5. Assert the fake upstream received **exactly** the canary in the right header for each call. This proves the path works, so the test cannot pass by everything quietly failing.
  6. Scan after exit, and again after the guard: `clean`.
  7. Revoke at the broker **mid-phase**, while the agent process is still alive. Start a timer and retry each call. Assert a broker 403, with no new request at the fake upstream, within 60 s.
- **Then:** delete the legacy host-keyed entry, update the ADR-024 matrix, and flip local docker to `BrokeredCredentials` if H8 is yes.

### PR 8 (syntropic137), remote reachability. Lands only after PR 7.

- The Envoy TLS listener, with its certificate from settings.
- `SYN_BROKER_URL` and the authorities per backend kit, replacing the default at `packages/syn-adapters/src/syn_adapters/workspace_backends/service/workspace_service.py:267`.
- The compose and tunnel route.
- The remote egress allowlist (D5).
- *Exit:* the PR 7 end-to-end test, re-run with the workspace on a network with **no route to `agent-net`**, through the TLS hostname.

### PR 9 (syntropic137), #1735 acceptance run. Gates the remote default.

- Run a real `sdlc-implement-v3` on the first non-local backend (E2B or the microVM pool, whichever ships first), with **real** model, git and gh credentials.
- Record a `CanaryReport` at every phase boundary of every phase.
- Revoke one workspace at the broker mid-phase, and record time-to-denial from the audit lines.
- *Exit:*
  - every report is `clean`, none `incomplete`
  - the workflow's PR exists on GitHub
  - revocation took effect in ≤ 60 s
  - the evidence is attached to #1735
- No remote backend kit may default to running real work until this passes.
- This PR depends on a remote provider existing, which is outside this plan.

## 5. Maintenance cost

**Added:**

- `syn_tokens.broker`, about 250 LOC with three Lua scripts
- the policy and presenter Protocols
- `github_presentation`, which is a move rather than new logic
- one route table with its fitness test
- the scanner and `SendGuard`
- the injector becomes a Redis-backed hot path that must be load-tested at each north-star step

**Removed:**

- the Phase-1 no-ops
- the plaintext-keyed, execution-scoped vend
- the host-keyed registry
- the 40-minute exec for renewal in brokered mode
- the agent-controlled audit header

**Where future change lands:**

- A harness CLI release changes only an AW presenter, whose CI catches it.
- A gh or git behaviour change lands in `github_presentation` and the GitHub route.
- A new upstream class is one `TokenType`, one route row and one presenter.

## 6. Rejected alternatives

1. **A new standalone broker service.** It duplicates Envoy's TLS, routing and fail-closed overwrite, and leaves two proxies to keep consistent. The owner also directed extending the existing proxy.
2. **A credential helper or `apiKeyHelper` that fetches a real short-lived upstream token.** The agent can call it and hold a live token. It also needs a new binary in the image.
3. **Signed JWT capabilities.** The 60 s revocation needs a server-side lookup anyway, so the signature adds key management and buys nothing.
4. **Per-execution mTLS client certificates as identity.** This needs CA operations and CRL/OCSP freshness against 60 s, and harness CLIs do not reliably present client certificates. Box-level mTLS stays an option (H4).
5. **One capability for all classes, or merging with the ADR-072 platform token.** A stolen model capability could then push code, and the platform token's on/off switch would be coupled to the broker.
6. **Raw credentials in the sandbox with restricted egress, or vendor-side secret injection.** These do not meet #1735 and are residency decisions (`docs/research/2026-10-08-remote-executor-e2b.md:374-377`).
7. **`HTTPS_PROXY` interception for everything.** It puts a CA in every image and intercepts model traffic. It is kept only as gh's fallback.
8. **Caching positive lookups in the injector.** It adds a second number that must stay under 60 s. Revisit only if PR 4's load test demands it.
9. **The broker unwrapping CLI-specific wire formats.** That puts harness knowledge on our side of the boundary. D6's issue-time encoding replaces it.
10. **A generic shared token framework for platform and broker grants.** They share hashing but not their authorization decisions.

## 7. Risks

| Risk | Signal or mitigation |
|---|---|
| S1 finds no Claude API-key presentation that passes the CLI's check | The S1 exit test fails. The class stays local-only, and #1735 is reported blocked for Claude, not worked around |
| A CLI update changes its format check | AW presenter CI (PR 6) fails on the image bump, before release |
| gh enterprise mode misparses the repo or rewrites `hosts.yml` with a real token | The S2 matrix; the D13 scan of `~/.config/gh` |
| The injector becomes the throughput ceiling. Envoy's global local rate limit is 10 rps sustained (`docker/sidecar-proxy/envoy.yaml:272-289`), already low for 20 concurrent | PR 4 p99; `ext_authz.error` stats; 429s in the access log |
| A Redis outage fails every model call (fail-closed) | 403 spikes with `reason=store_unavailable` |
| Live GitHub tokens in AOF-persisted Redis | H6 |
| In-flight streams outlive revocation (300 s routes) | PR 7 measures new-request denial; H3 decides streams |
| A capability is exfiltrated and used elsewhere until its deadline | Audit shows one `workspace_id` from two sources; H4 source binding; D5 egress |
| Grant revoked, or bounded, before the salvage push | D9 grace; PR 3 and PR 5 tests |
| Scanner cost at 1,000 concurrent: every writable byte streamed out three times per phase | Measure in PR 7. `report` mode remotely until measured. Restricting to changed files is a follow-up, never a silent reduction in coverage |
| A scan in a hostile sandbox is fooled | Accepted as a stated limit; D12 carries the guarantee |

## 8. Verification

These gates run on every PR:

```
just preflight-agent
uv run pytest -m unit -q
```

What each PR adds, and what reverting it would break:

| PR | Command | Reverting the change fails |
|---|---|---|
| 2 | `uv run pytest -m unit packages/syn-tokens -q`, plus the Redis-backed interleaving tests | (a) hashing, (b) per-workspace revoke, (f) atomicity |
| 3 | `uv run pytest -m unit packages/syn-adapters/src/syn_adapters/workspace_backends -q` | the two-workspace delivery test (restoring the no-op or the execution-keyed revoke) |
| 4 | `uv run pytest docker/token-injector/tests -q`; `uv run pytest -m architecture ci/fitness/infrastructure -q`; the real-Envoy access-log test | route↔class agreement; spoof and strip negatives; forged audit header |
| 5 | unit tests plus the hardened quarantine-push integration test | direct injection restored; the fixed github.com-only settings restored |
| 6 | AW CI; the syntropic137 round-trip test | any encoder/broker mismatch |
| 7 | detector tests; the end-to-end test | an always-clean scanner; PR 4 or PR 5 reverted |
| 8 | the end-to-end test on an isolated network |, |
| 9 | the acceptance run (§4) |, |

Every new Python test module carries the `unit` marker, or `architecture` under `ci/fitness/`.

## 9. Acceptance gaps, stated

- Claude OAuth/Max and Codex ChatGPT mode stay unbrokered and remote-refused until H1 and H2 are answered.
- In-flight streams after revocation, until H3 is answered.
- The scan's limits (D13). The guarantee rests on D12.
- PR 9 needs a remote backend that this plan does not build.

## 10. Out of scope

- The session-store write token and the ADR-072 platform token are our own scoped capabilities. The scan lists them as known-and-exempt (H7).
- Closing open local `agent-net` egress (#1794).
- Enforcing spend at the broker.
- An operator revocation verb in the CLI. Teardown and cancel revoke, and PR 9 uses an internal call.
- Envoy's global rate limit.
- The microVM and E2B providers themselves.

## 11. Needs a human decision

- **H1.** May the broker header-proxy Claude OAuth/Max (ToS)? Default: refused remotely (`docs/adrs/ADR-024-setup-phase-secrets.md:531`).
- **H2.** The same question for Codex ChatGPT mode, whose refresh-token rotation would move to the broker. Default: refused.
- **H3.** Does the 60 s revocation bar cover in-flight streams? Cutting them needs a `max_stream_duration` of 60 s or less, which breaks long generations.
- **H4.** The remote→broker path: Cloudflare tunnel or tailnet? Is box mTLS or a source allowlist required? Is direct github.com egress dropped (D5's change from E2B Decision 6)?
- **H5.** Does a per-box Envoy holding upstream keys on a microVM host count as "off-host"? Default: a central broker.
- **H6.** Are live GitHub tokens acceptable in AOF-persisted Redis, or should grants use a separate non-persisted Redis?
- **H7.** Should the canary also count the session-store and platform tokens?
- **H8.** Flip local docker to brokered once PR 7 is green? Recommended: yes.
- **H9.** Confirm that #1735 replaces the closed #725 as the owner of "Tier 1".
- **H10.** Confirm that git/gh presentation stays in syntropic137 (`github_presentation`) rather than agentic-workspace, as GitHub-protocol configuration rather than harness knowledge.

---

## Review disposition

| finding | accepted / rejected | what changed |
|---|---|---|
| B1 seam lacks identity, deadline, return channel; two issuers | **Accepted.** Verified: `vend_token` takes no workspace id (`packages/syn-domain/src/syn_domain/contexts/orchestration/_shared/ports.py:127-140`); the injection adapter discards the handle and returns only a result (`packages/syn-adapters/src/syn_adapters/workspace_backends/tokens/token_injection_adapter.py:106`, `:132-137`); every workspace gets the same handle id (`packages/syn-adapters/src/syn_adapters/workspace_backends/docker/shared_envoy_adapter.py:75-79`); provisioning defaults to ANTHROPIC only (`packages/syn-adapters/src/syn_adapters/workspace_backends/service/workspace_service.py:517-519`); and the 300 s default TTL would expire mid-phase (`packages/syn-adapters/src/syn_adapters/workspace_backends/service/workspace_service.py:112`) | Added D10: one issuer (the vending port → `BrokerGrantService`) with `configure_tokens` a documented no-op; class selection via `CredentialRequest`; `GITHUB_GIT` / `GITHUB_API` members; `InjectedCredentials` / `BrokerGrantSet` return channel; `SYN_BROKER_GRANT_MAX_TTL_S`; deadline bounding in `stream()`. PR 3's exit test now provisions two workspaces with all classes |
| B2 quarantine push does not keep working | **Accepted.** Verified: hardened git uses `HOME=/nonexistent` and a fixed github.com settings tuple (`packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/workspace_git.py:182`, `:194-207`) | Added D9: `provisioned_remote_settings(git_authority)` fed from host state, with SSH rewrites pointed straight at the broker (insteadOf does not chain) and a deadline + interrupt-budget grace for git grants. PR 5 adds a real hardened quarantine-push integration test. The draft's "unchanged" claim is removed |
| B3 wrapper contradicts hash contract | **Accepted** | D6 now has issue-time encoding: the host calls the presenter's `wire_credential` before hashing, and the broker hashes the standard auth-scheme value with no CLI unwrapping. S1's exit test checks the hash, and PR 6 adds a real-presenter round-trip test |
| B4 scanner not a verified detector | **Accepted** | D13 specifies cmdline coverage, writable-mount coverage, host-side matching, Basic-form base64 at three alignments, `incomplete` status with gaps, fail-closed pre-launch, post-exit outcomes and stated limits. D12 adds `SendGuard` as the constructive guarantee. PR 7 adds planted-canary positive tests |
| B5 PR 7/8 not the acceptance criterion | **Accepted.** I could not read #1735 myself; the requirement is stricter, so it is adopted regardless | PR 7 is relabelled a component test and now provisions through the production handler path, with mid-phase revocation. Added PR 9: a real `sdlc-implement-v3` on a remote backend, which gates the remote default. Scope is stated as API-key-only, and §9 lists the acceptance gaps |
| B6 revocation not atomic | **Accepted.** Verified read-then-write at `packages/syn-adapters/src/syn_adapters/platform_access/__init__.py:216-224` | Added D11: Lua scripts for `set_upstream`, `bound_to_deadline` and `revoke_workspace`, with an authoritative TTL and an atomic index. PR 2 test (f) runs deterministic interleavings on real Redis. H3 stays separate for streams |
| I1 gh routing semantics | **Accepted** | D3 makes `GITHUB_API` carry exactly the one token today's routing selects (`packages/syn-adapters/src/syn_adapters/workspace_backends/service/setup_phase_secrets.py:323-363`), so there is no GraphQL parser. The S2 matrix covers `GH_REPO`, `clone_repos: false`, repo-less workflows, explicit URLs and GraphQL. D10 requests `GITHUB_GIT` for `clone_repos: false` too |
| I2 trusted routing identity and stripping | **Accepted.** Verified: `x-forwarded-host` is preferred (`docker/token-injector/token_injector.py:153`) and forwarded (`docker/sidecar-proxy/envoy.yaml:258-262`) | PR 4: the class comes from authority plus normalized path; `x-forwarded-host` is ignored and no longer forwarded; `x-envoy-auth-headers-to-remove` strips the capability header; added spoof, wrong-authority and conflicting-header tests. Legacy coexistence is distinguished by listener; remote ingress (PR 8) lands only after PR 7 deletes legacy |
| I3 audit wire contract | **Accepted.** Verified: the injector emits headers only (`docker/token-injector/token_injector.py:173-177`); the log reads a request header (`docker/sidecar-proxy/envoy.yaml:99`) | D7 specifies the audit response headers, `dynamic_metadata_from_headers`, and the access-log format string. PR 4 adds a real-Envoy access-log test with a forged header. Audit tests cover denials and exclude upstream values |
| I4 keep reused pieces; minting owner; no generic framework; citations; E2B allowlist; gh owner | **Accepted** | D3 keeps `SetupPhaseSecrets` and the ledger as the only minting owner. Rejected #10 rules out a shared framework. The credential_keeper citation is the full path. Branch-only docs are named by ref. D5 records dropping github.com from E2B's allowlist as a deliberate change (H4). gh/git presentation has one owner, `github_presentation`, with H10 to confirm the boundary reading |

## Readiness

S1, S2 and PRs 1-5 are ready to implement now. Turning on the Claude API-key class depends on S1's outcome, not on a human. Brokering Claude OAuth/Max and Codex ChatGPT mode is **blocked on human decisions H1 and H2** (whether OAuth may be header-proxied), and PR 8's network path is blocked on **H4** (tunnel vs tailnet, and whether direct github.com egress is dropped).

