# Action items for you (ADR-067 model pricing + toolchain freshness)

**Created:** 2026-08-16
**Context:** [ADR-067](../adrs/ADR-067-model-registry-and-cost-attribution.md) |
[AP spec](20260816-spec_ap-model-registry-changes.md) |
[Release plan](../testing/output/RELEASE-PLAN-v0.25.5.md)

Everything here needs *you* - credentials, accounts, or a policy decision. Nothing else
is blocked on these; implementation proceeds up to the point where it needs one.

---

## 1. Add `CODEX_AUTH_JSON` to 1Password  (blocks: codex runs on dev/selfhost)

**Vault:** `syn137-dev` -> item **`syntropic137-config`** (id `iiodbjwmoffgw4olocha2f6vra`)
**Field label:** `CODEX_AUTH_JSON` (exact - the resolver matches on label)

Value is the one-line contents of `~/.codex/auth.json`. Generate it without printing the
secret:

```bash
just codex-auth-clip          # copies the raw value to the clipboard
```

Then paste into the 1Password field.

Confirmed present on that item already: `CLAUDE_CODE_OAUTH_TOKEN`, `SYN_GITHUB_APP_ID`,
`SYN_GITHUB_APP_NAME`, `SYN_GITHUB_PRIVATE_KEY`, `SYN_GITHUB_WEBHOOK_SECRET`,
`SYN_API_PASSWORD`, `SYN_DOMAIN`, `CLOUDFLARE_TUNNEL_TOKEN`.
Missing: **`CODEX_AUTH_JSON`** (this item), and `ANTHROPIC_API_KEY` (not needed - the
OAuth token is the path in use).

No code change required: `ENV_CODEX_AUTH_JSON` is already in `_KEYS` in
`scripts/op_env_export.py`, so `just dev` picks it up once the field exists.

**Repeat for the selfhost vault** (`syntropic137`) if you want codex working on the
selfhost stack too - same field name.

- [ ] Added to `syn137-dev`
- [ ] Added to `syntropic137` (selfhost)

---

## 2. Decide the CI auth mode for the harness smoke test  (blocks: ADR-067 D8 test gate)

The weekly harness-version job must prove the new image still *works*, not just that the
packages installed. That means running `claude -p` and `codex exec --json` against real
credentials in agentic-primitives CI.

The problem: codex production auth is a **ChatGPT-subscription `auth.json`** - a personal
user credential. An OpenAI **API key** is the CI-appropriate credential, but model
availability differs by auth mode (`gpt-5.6-sol` is offered under ChatGPT sign-in; there
is a documented "model not supported when using Codex with a ChatGPT account" error for
other ids). So an API-key test can pass while the production auth path is broken.

| Option | Fidelity to prod | Cost / effort |
|---|---|---|
| **A. Dedicated CI ChatGPT account** (recommended) | matches prod exactly | needs a second account; check OpenAI terms on automated use |
| B. Test both auth modes | highest | two credential sets to manage |
| C. API key only | **does not cover the prod auth path** | simplest; needs a manual check when auth behaviour changes |

- [ ] Decision made: ______
- [ ] If A/B: CI ChatGPT account created, terms checked

---

## 3. Add CI secrets to agentic-primitives  (blocks: D8 test gate)

Separate store from 1Password. `AgentParadise/agentic-primitives` -> Settings -> Secrets
and variables -> Actions:

- [ ] `ANTHROPIC_API_KEY` or `CLAUDE_CODE_OAUTH_TOKEN` (for the `claude -p` smoke test)
- [ ] codex credential, per the decision in item 2

Note this job spends real tokens every week. Keep the smoke test to a trivial prompt
(one short completion per harness) so the recurring cost stays negligible.

- [ ] Weekly token budget acceptable / capped

---

## 4. Confirm OpenRouter terms  (blocks: nothing today; do before relying on it)

We consume `https://openrouter.ai/api/v1/models` (public, unauthenticated) in CI, and
**vendor a committed snapshot** - so runtime never calls them and the dependency is
build-time only. Their pricing-data licence is not stated on the endpoint.

- [ ] Terms reviewed / acceptable for this use
- [ ] If not: fall back to `pydantic/genai-prices` (MIT, release-tagged) - same pipeline shape

---

## 5. ~~GitHub App credentials~~ - NOT BLOCKED (corrected 2026-08-16)

**This was my error.** I reported §5/§7 as blocked after checking the repo `.env` *file*,
where these are empty by design. The running container has them, resolved from 1Password
at `just env-up` time:

```
SYN_GITHUB_APP_ID: SET        SYN_GITHUB_PRIVATE_KEY: SET (2236 bytes)
SYN_GITHUB_APP_NAME: SET      SYN_GITHUB_WEBHOOK_SECRET: SET (40 bytes)
```

Repo registration and trigger round-trips are runnable against the on-demand env whenever
wanted. Nothing needed from you.

One genuine open question remains: the repo App (`syn137-engineer-development`, id
3018363) differs from the published selfhost stack's App (`syntropic137-npx-test`).
Which one owns the private sandbox repo matters for which stack can fire triggers on it.

Note the published selfhost stack (`syn137-api` on :8137) *does* show these as empty env
vars, because that stack mounts the key as a Docker **secret file** rather than an env
var. Not a defect, just a different injection path - and a reason not to compare the two
stacks by `printenv`.

- [ ] Sandbox repo App ownership confirmed (only if §7 is to be run against selfhost)

---

## 6. Release sequencing decision  (blocks: cutting a release)

Per the release plan, the minimum viable cut is Track A (codex compose passthrough,
already fixed and uncommitted; plus the VSA gate, ~1.5h). The pricing work is larger.

- [ ] Cut on Track A + Phase 0 (correct rates), pricing refactor in the next release
- [ ] Or hold the release until Phases 0-2 land

---

## Not blocked on you - proceeding now

| Phase | Work | Repo |
|---|---|---|
| 0 | Current model ids + verified rates; repoint `haiku`/`sonnet`/`opus` | syn137 |
| 1 | `PricedAmount`, fail-loud, expose unpriced through the API | syn137 |
| 2 | Rate-at-write; delete read-time pricing | syn137 |
| 3-4 | OpenRouter fetch job, schema + CI enforcement, codegen | both |

Phases 3+ can be written and reviewed without credentials; only the D8 *test gate*
(item 2/3) actually needs them to run.
