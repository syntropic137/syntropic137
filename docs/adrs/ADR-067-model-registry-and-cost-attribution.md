# ADR-067: Model registry as source of truth, and rate-at-write cost attribution

- **Status**: Proposed
- **Date**: 2026-08-16
- **Issue**: #780 (placeholder GPT-5.6 rates), #812 (phase cost disagreement); class-level follow-up to #788
- **Related**: ADR-018 in agentic-primitives (model registry), ADR-020 (bounded contexts), ADR-060 (restart-safe adapters), ADR-066 (separation of concerns)

## Context

Cost and model attribution are the product's core value. Both are currently wrong in ways
that are invisible to users. Four defects, all verified live on `main` @ `da22a56b`:

**0. Both hand-maintained catalogs are already stale. This is the root problem.**

| Catalog | Newest Claude models it knows | Reality (2026-08) |
|---|---|---|
| syn137 `MODEL_PRICING_TABLE` | Opus 4, Sonnet 4, Haiku 3.5 | Claude 5 family (Opus 5, Sonnet 5), Haiku 4.5 |
| agentic-primitives registry | the 4.5 family | as above |

syn137 is roughly two generations behind; the registry meant to fix it is one generation
behind. **Two independent hand-maintained catalogs, both stale, and one of them was the
remedy for the other.** No amount of "add the missing cards" fixes this - it has already
been tried twice and decayed both times.

The conclusion that drives this ADR: **the catalog must be sourced automatically and
verified mechanically, and any model it does not know must fail loudly rather than be
priced by guess.** Correctness cannot depend on a human noticing a vendor announcement.

**1. Two model catalogs, neither complete.**
`lib/agentic-primitives` already defines a model registry (ADR-018, Accepted 2025-12-02):
three-tier aliases, one schema-validated YAML per model, 20+ cards across
anthropic/openai/google, and an agent-facing `UPDATE_GUIDE.md`. `grep -rn "providers/models"
packages/ apps/` returns **zero hits** - syn137 ignores it and hardcodes a parallel table
in `packages/syn-shared/src/syn_shared/pricing/__init__.py`.

| | AP registry | syn137 table |
|---|---|---|
| Cache pricing | **absent** | present |
| Codex models | `gpt-5.1-codex` | `gpt-5.6` (placeholder, #780) |
| `gpt-5.6-sol` (actually run) | absent | absent |
| Consumed by syn137 | **no** | yes |

Cache pricing is not optional: in a measured codex run, `cache_read` was **159,744 of
178K tokens (89%)**. A catalog without it cannot price anything accurately.

The AP registry's JSON schema is also broken: it requires `name`/`family`/`api`/
`pricing.input` while every card uses `full_name`/`api_name`/`pricing.input_per_1m_tokens`.
**It matches no card, and nothing enforces it** (no CI job, no test).

**2. Alias drift is mis-attributing every Claude run, and over-charging `opus` by 3x.**

syn137's `ModelId` enum contains **no 4.5 models at all**. All three aliases resolve to
superseded models:

| alias | syn137 resolves to | rate used | actually runs | real rate | error |
|---|---|---|---|---|---|
| `haiku` | `claude-3-5-haiku-20241022` | $1 / $5 | `claude-haiku-4-5-20251001` | $1 / $5 | correct by luck |
| `sonnet` | `claude-sonnet-4-20250514` | $3 / $15 | `claude-sonnet-4-5-*` | $3 / $15 | correct by luck |
| **`opus`** | **`claude-opus-4-20250514`** | **$15 / $75** | **`claude-opus-4-5-*`** | **$5 / $25** | **3x over-charge** |

Every `opus` run recorded to date is inflated threefold. Two of the three are right only
by coincidence.

This is also the decisive argument for D2. A vendor did not "change a price": Anthropic
shipped Opus 4.5 at a third of Opus 4's rate. But because syn137 resolves through a
mutable **alias**, that lands in the data exactly as a retroactive price change would.
Alias drift makes "prices never change" false in practice even when it is true per model.

**3. Cost is computed at read time, so any price correction rewrites history.**
`ObservabilityCollector.record_token_usage` persists
`{input_tokens, output_tokens, cache_creation_tokens, cache_read_tokens, model}` -
**no rate**. Read paths recompute from raw tokens
(`execution_cost/timescale_query.py:303,358`, `session_cost/timescale_query.py:206`).

Therefore a price change retroactively re-prices every historical run. This is not a
hypothetical about vendor price cuts; the three real triggers are all imminent and
deliberate:
- correcting the `TODO(#780)` gpt-5.6 placeholder rates
- adding a previously-unknown model (every `$0.00` codex run acquires a cost)
- alias drift (defect 2, already live)

It is also a Lane-2 violation: observability is append-only fact, not recomputed derivation.

**4. Unknown models fail silently.** `resolve_model_pricing` returns `None` with no log.
Downstream that becomes `total_cost_usd: "0"`, `"$0.00"` - indistinguishable from free.
`unpriced_observation_count` exists in the domain read models but `grep -rn "unpriced" apps/`
returns **0 hits**: it reaches no API, no CLI, no dashboard. There is no nullable cost field
anywhere in the API surface. Separately, `syn_shared.pricing.get_model_pricing()` still does
`resolve_model_pricing(x) or MODEL_PRICING_TABLE[DEFAULT_MODEL_ID]`, silently pricing any
unknown model as Sonnet 4; `syn_tokens.SpendTracker` (wired at `_wiring.py:919`) uses it for
budget enforcement.

## Decision

### D-1. Harness-reported cost is a cross-check, never the source of truth

Both cost paths currently prefer the CLI-reported `sdk_cost`
(`session_cost/timescale_query.py:142-144`, `execution_cost/timescale_query.py:337-351`),
falling back to the table only when it is NULL. That looks like a safe design and is not.

Anthropic's own documentation (`code.claude.com/docs/en/agent-sdk/cost-tracking`,
retrieved 2026-08-16) states that `total_cost_usd` is computed **client-side from a price
table bundled at build time**, drifts when pricing changes or when the installed version
does not recognise a model, and carries the explicit instruction:

> "Do not bill end users or trigger financial decisions from these fields."

It is therefore a stale table too - just Anthropic's rather than ours. Codex, by contrast,
reports **no cost at all** (confirmed against official docs and empirically: a 31-line
`codex exec --json` stream from CLI 0.147.0 contains zero occurrences of "model" and no
cost field; `turn.completed` carries only
`{input_tokens, cached_input_tokens, output_tokens, reasoning_output_tokens}`).

**Decision:** treat what the harness reports about *facts* (model, tokens) as
authoritative, and what it reports about *money* as advisory. syn137 computes cost from
its own verified rates for every provider. A divergence between our computed cost and a
harness-reported cost is logged as a signal that one of the two tables is stale - useful,
but never load-bearing.

This unifies the two harnesses into one shape:

```
harness supplies:  model + tokens        -> facts, trusted
syn137 computes:   cost = tokens x rate  -> money, ours
harness cost:      cross-check only
```

Codex's model is recoverable even though it is absent from stdout: it appears in the
on-disk rollout file (`~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl`) as
`turn_context.model` (verified: `"gpt-5.6-sol"`), in `session_meta.model_provider`, and to
in-process tracing plugins as `turn.model`. Pinning `--model` (D6) is simpler still, since
then we know it by construction.

### D0. The catalog is machine-sourced and machine-verified, never hand-curated

This decision outranks the rest. Hand-maintenance has demonstrably failed twice, so every
other decision here is void if a human has to notice a model launch.

**No vendor publishes machine-readable pricing.** Verified 2026-08-16: Anthropic's
`GET /v1/models` returns ids, display names, token limits and capability flags but **no
price field**; OpenAI's `GET /v1/models` is weaker still (id, created, owned_by,
shutdown_date). Claude Code's bundled table exists but lives inside a ~300 MB proprietary
binary behind mangled identifiers. **Any pricing pipeline must therefore consume a
community source** - there is no first-party option to wait for.

**Chosen source: the OpenRouter models API** (`https://openrouter.ai/api/v1/models`),
vendored as a committed snapshot. Verified directly against vendor docs on 2026-08-16
(413 models, no auth required):

| Model | OpenRouter (per 1M) | Vendor pricing page | |
|---|---|---|---|
| `anthropic/claude-opus-5` | $5 / $25, cache r $0.50 w $6.25 | $5 / $25, r $0.50 w $6.25 | match |
| `anthropic/claude-sonnet-5` | $2 / $10, r $0.20 w $2.50 | $2 / $10, r $0.20 w $2.50 | match |
| `anthropic/claude-haiku-4.5` | $1 / $5, r $0.10 w $1.25 | $1 / $5, r $0.10 w $1.25 | match |
| `openai/gpt-5.6-sol` | $5 / $30, r $0.50 w $6.25 | $5 / $30, r $0.50 w $6.25 | match |

It is the only evaluated source current on **both** generations, and it additionally
carries `:batch` (50% off) and `-fast` variants as first-class rows, covering two cost
dimensions syn137 models nowhere today.

Rejected alternatives: **LiteLLM** is missing the entire GPT-5.6 family, and separately had
a March 2026 PyPI supply-chain compromise (CVE-2026-33634 / CISA KEV); **Helicone** is
stale by two model generations; **models.dev** is provider-keyed, making "the price of
Opus 5" ambiguous. OpenRouter is the single source; no second data dependency is taken.

Correctness is defended by validation rather than by a second source:
- **Schema validation** on the fetched payload before it is written to the snapshot.
- **Sanity ranges** per field, so a malformed or hostile value (a $5 model becoming $5000,
  or dropping to $0) fails the job instead of shipping.
- **PR diff review** - every rate change arrives as a reviewable diff, not a silent update.
- **Spot-check against the vendor pricing page** when a diff touches a model in active use.

If drift ever becomes a concern, a second source (`pydantic/genai-prices`, MIT and
release-tagged) can be added as a cross-check without changing the pipeline shape.

1. **Automated discovery.** A scheduled job fetches the OpenRouter models API, filters to
   the models this platform actually executes, normalises to the card schema, and diffs
   against the committed snapshot. Any new, renamed, retired, or re-priced model opens a
   PR. The snapshot is what ships - runtime never calls the network or parses vendor JSON.
2. **Never invent a rate.** A scaffolded card carries `is_placeholder: true` and, if the
   rate could not be read from the source, `null` rates. A placeholder rate never produces
   a confident cost - it flows through as `pricing_status: "placeholder"` (D2/D3), and an
   absent rate makes the run `unpriced` (D4). Guessing is the failure mode that produced
   the 3x `opus` over-charge.
3. **Mechanical staleness.** CI fails when any card's `verified_at` exceeds a threshold, or
   when a vendor exposes a model with no corresponding card. Staleness becomes a red build,
   not a discovery made months later during a cost investigation.
4. **Alias resolution is data, not code.** `haiku`/`sonnet`/`opus` resolve through the
   registry's `current_models` map, refreshed by the same job. syn137 hardcodes no alias
   mapping - that hardcoding is precisely what left `opus` pointing at a superseded model.

Human review remains in the loop (approving a PR), but human *vigilance* does not.

### D1. The agentic-primitives model registry is the single source of truth

syn137 stops hand-maintaining a pricing table. `MODEL_PRICING_TABLE` becomes a **generated
artifact** produced from the registry, in the same spirit as the existing
OpenAPI -> `api-types.ts` pipeline. Hand-editing it becomes a CI failure.

Required changes in `agentic-primitives` (prerequisite, ships first):

1. Extend the model-card schema with cache pricing:
   `cache_read_per_1m_tokens`, `cache_creation_per_1m_tokens`.
2. Rewrite `providers/.schemas/model-config.schema.json` to match the cards as they are
   actually written, and **enforce it in CI** over every file in `providers/models/`.
3. Add provenance to every card: `verified_at` (date), `source` (vendor doc URL),
   `is_placeholder` (bool). A guessed rate must not be indistinguishable from a verified one.
4. Add the codex models actually in use, including `gpt-5.6-sol`.
5. Publish a flattened `models.json` as a release asset under a `models/vX.Y.Z` tag. AP
   already tags per component (`sdlc/v1.4.1`, `observability/v0.2.2`) via `plugin-tag.yml`,
   so this reuses existing machinery.
6. Extend the existing `claude-cli-version-check.yml` cron pattern to models: diff vendor
   model lists against `providers/models/` daily and open an issue or a scaffolded PR.
   Maintenance becomes reviewing a PR, not monitoring vendor blogs.

### D2. Resolve pricing once, at write time, and persist the rate on the observation

`ObservabilityCollector` resolves pricing when it records usage, and persists the outcome:

```python
data = {
    "input_tokens": ..., "output_tokens": ...,
    "cache_creation_tokens": ..., "cache_read_tokens": ...,
    "model": "<resolved immutable api_name, never an alias>",
    "model_source": "explicit" | "workflow_default" | "provider_default",
    "rate_input_per_1m": Decimal | None,
    "rate_output_per_1m": Decimal | None,
    "rate_cache_read_per_1m": Decimal | None,
    "rate_cache_creation_per_1m": Decimal | None,
    "cost_usd": Decimal | None,
    "pricing_status": "priced" | "unpriced_unknown_model" | "unpriced_no_rate" | "placeholder",
    "pricing_source_version": "<models.json version>",
}
```

Read paths then `SUM(cost_usd)` and count non-`priced` rows. Read-time pricing is deleted.

Consequences:
- Historical costs are immutable and auditable; a rate correction only affects future runs.
- The multi-model-collapse bug (`MAX(data->>'model')` in `session_cost/timescale_query.py:49`)
  disappears, because cost is per-observation.
- The silent-zero class becomes unrepresentable (see D3).
- `model` stores the **resolved immutable id**, not the alias, closing defect 2.

### D3. `PricedAmount` is the only type a cost calculator may return

```python
@dataclass(frozen=True)
class PricedAmount:
    cost: Decimal | None
    status: PricingStatus          # priced | unpriced_unknown_model | unpriced_no_rate | placeholder
    model: str | None
```

No cost function may return a bare `Decimal`. This makes `Decimal("0")`-on-unknown
structurally impossible and carries the reason to the API boundary.

### D4. Fail loud, never substitute

- Delete `get_model_pricing()`, `calculate_cost(model=DEFAULT_MODEL_ID)`, and
  `DEFAULT_MODEL_ID`. Replace with `resolve_model_pricing() -> ModelPricing | None` and
  `require_model_pricing() -> ModelPricing` (raises). While an `or DEFAULT` resolver is
  importable, something will import it - `SpendTracker` already does.
- Remove the prefix-match heuristic that prices an unrecognised dated id at its family's
  current rate; an unknown id is unknown.
- `logger.warning` at every unpriced resolution, with model id and session id.
- A Claude alias on a codex phase raises `ValueError` instead of being silently dropped.
- Invert the three tests that enshrine the fallback:
  `syn-tokens/tests/test_spend.py:77-81`, `pricing/test_pricing_codex.py:27-30`,
  `session_cost/test_cost_calculator.py:87,91`.

### D5. Surface unpriced state through the API

Add `pricing_status` and `unpriced_observation_count` to cost responses in
`apps/syn-api/src/syn_api/types.py`; regenerate `api-types.ts`. CLI and dashboard render
`unpriced` (or `-`) rather than `$0.00`. Optional `SYN_COST_STRICT=true` fails a phase that
would complete unpriced, for analytics-critical deployments.

### D6. Pin the codex model

`_build_codex_command` currently omits `--model`, so codex runs an account default that is
never observed. Codex never reports its model: a full 31-line `codex exec --json` stream
from CLI 0.147.0 contains **zero** occurrences of "model"; `turn.completed` carries usage
only. Exact codex pricing is therefore achievable only by pinning.

Pin from an explicit setting (`SYN_CODEX_MODEL`, default `gpt-5.6-sol`) and record it.
Verified live: a phase with `model: gpt-5.6-sol` ran to completion and recorded
`agent_model = gpt-5.6-sol`. Note that under ChatGPT-account auth codex **rejects**
`gpt-5.6` - the only GPT id currently in the syn137 table - so the table today prices a
model this deployment cannot run and cannot price the one it does.

### D7. Layered resolution, so model updates need no redeploy

| Layer | Source | Purpose |
|---|---|---|
| 1 | Baked-in snapshot generated from the registry at build time | Offline floor; always works |
| 2 | Postgres `model_pricing` table, rows keyed by `effective_from` + `source_version` | What the app reads; restart-safe; time-versioned |
| 3 | Scheduled `ProcessManager` refresh pulling `models.json` from AP releases | New models land with no syn137 release |
| 4 | Operator override: `SYN_MODEL_PRICING_OVERRIDE_JSON` or an admin endpoint | Same-hour patch when a model drops |

Each layer falls back to the one below: **no hard network dependency at runtime**.

Layer 2 rows are append-only and time-versioned. Because D2 already froze the rate onto
each observation, layer 2 is only consulted for *new* observations; historical cost never
depends on it. This is precisely why D2 must land before layers 3-4.

### D8. Toolchain freshness: harness versions follow the same pattern, gated by a real test

Model pricing, model cards, and **harness CLI versions** are the same problem wearing
three hats: an external thing moved and nothing told us. The mechanism is identical -
scheduled check, PR, immutable artifact, consumer pulls on demand, record what was used.

Current state (verified 2026-08-16):

| | Pinned in the image | Actually current |
|---|---|---|
| Claude CLI | `CLAUDE_CLI_VERSION=2.1.126` | 2.1.232 |
| Codex CLI | `CODEX_CLI_VERSION=0.144.6` | 0.147.0 |

`build-workspace-images.yml` has **no schedule** (push-with-path-filter and
`workflow_dispatch` only), and `claude-cli-version-check.yml` watches **Claude only** -
which is precisely why codex drifted furthest.

**In agentic-primitives:**

1. **Weekly cron** checks npm for newer `@anthropic-ai/claude-code` **and** `@openai/codex`
   and opens a PR bumping the `ARG` versions.
2. **The PR must not merge on a green build alone.** Building an image proves the packages
   installed, not that the harness still works. CI must run a **programmatic smoke test
   against the new image with real API keys**: invoke `claude -p` and `codex exec --json`
   headlessly, assert a non-empty result and a well-formed stream (for codex: a terminal
   `turn.completed` carrying a `usage` block). A CLI can install cleanly and still have
   changed its flags, output schema, or auth behaviour - this arc has already been bitten
   by exactly that.
3. On merge, publish an **immutable tag** (date- or digest-based) in addition to moving
   `:latest`, so a specific toolchain is always addressable.

**In syn137:**

4. **Pull before create.** `IMAGES: 1` on docker-socket-proxy (#720/#727) already permits
   runtime pulls, but Docker only auto-pulls a **missing** image - a stack holding
   `:latest` locally never sees a new one. An explicit pull (a no-op when the digest
   matches) is what makes a floating tag actually float.
5. **Record the resolved image digest** on the workspace-provisioned event, alongside the
   harness versions and the model. Then "which toolchain produced this session" is
   answerable, and a behaviour change that arrived with a new image is diagnosable instead
   of mysterious.
6. **Configurable pinning.** `SYN_WORKSPACE_DOCKER_IMAGE` accepts a floating tag (default,
   auto-updates) **or an immutable tag/digest**, and an operator who pins gets exactly that
   image until they change it - no surprise upgrades. Same layered principle as pricing:
   a convenient default with a determinism escape hatch.

The pinning option is not a nicety. Auto-pulling `:latest` means a vendor CLI release can
change agent behaviour mid-flight with no release on our side; a workflow that worked
yesterday breaks and nothing in this repo changed. The digest record (5) makes that
diagnosable and the pin (6) makes it preventable.

## Consequences

**Positive**
- One catalog. Adding a model is one YAML plus a release; adding a harness is a directory.
- Historical costs immutable and auditable; reports reproducible.
- "Unpriced" is visible everywhere instead of masquerading as `$0.00`.
- Net *less* code: read-time pricing joins are deleted.
- Model updates without a syn137 release (layers 3-4).

**Negative / costs**
- Observation payloads grow by ~6 fields.
- Spans two repos; AP changes must ship first.
- Historical events written before D2 have no rate. They keep whatever cost was recorded
  and are marked `pricing_status: "legacy_unknown"` on read. **No backfill** - inventing
  rates for past runs is the same error in the opposite direction.
- `agent_model` will change from alias (`haiku`) to immutable id
  (`claude-haiku-4-5-20251001`). Dashboards grouping by model will show both until old
  data ages out.

## Implementation Order

Each phase is independently shippable and leaves the system better than it found it.

| Phase | Work | Repo | Blocking? |
|---|---|---|---|
| 0 | Add current model ids + verified rates; repoint `haiku`/`sonnet`/`opus` aliases | syn137 | **Yes - table has no current model** |
| 1 | D3 `PricedAmount` + D4 fail-loud + D5 API exposure | syn137 | Yes - removes all wrong numbers |
| 2 | D2 rate-at-write; delete read-time pricing | syn137 | Yes - prerequisite for any dynamic pricing |
| 3 | Registry: cache pricing, schema + CI enforcement, provenance, codex models | agentic-primitives | - |
| 4 | D1 codegen: generate `MODEL_PRICING_TABLE` from `models.json`; delete the hand table | syn137 | - |
| 5 | D6 pin codex model | syn137 | - |
| 6 | D7 layers 2-4 (DB + scheduled refresh + override) | syn137 | - |
| 7 | Model-release watch cron (OpenRouter fetch + validate + PR) | agentic-primitives | - |
| 8 | D8 harness-version cron **+ real-API-key smoke test gate**; immutable image tags | agentic-primitives | - |
| 9 | D8 pull-before-create, record image digest, configurable image pinning | syn137 | - |

Phases 0-2 are the release blockers: after them, every displayed number is either correct
or explicitly marked unknown. Phases 3-7 remove the maintenance burden.

## Verification

- An unknown model yields no numeric cost and `pricing_status != "priced"` (regression test).
- A codex run with a pinned model records that exact id and a non-zero cost.
- Correcting a rate in the registry does **not** change any historical cost (golden test:
  snapshot costs, bump a rate, re-query, assert unchanged).
- `grep -rn "unpriced" apps/` returns non-zero hits.
- Every card in `providers/models/` validates against the schema in CI.
- No production module imports a defaulting price resolver (extend
  `test_no_model_string_literals.py`; add `packages/syn-tokens/src` to its search roots).

## References

- ADR-018 (agentic-primitives): Model Registry Architecture - the existing three-tier design
- ADR-024: credential handling in workspaces
- ADR-066: separation of concerns
- Issue #780: confirm GPT-5.6 codex pricing (placeholder rates in the table today)
- Issue #788: codex mis-attributed to haiku (closed by #795; this ADR addresses the class)
- Issue #812: `cost_by_phase` can disagree with `total_cost_usd`
- `docs/retrospectives/2026-07-30-cost-computed-in-nine-places.md`
- `docs/testing/output/RELEASE-PLAN-v0.25.5.md` section B0/B0b - the audit behind this ADR
