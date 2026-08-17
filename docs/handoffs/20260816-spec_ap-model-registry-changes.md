# Spec: agentic-primitives model registry changes (for ADR-067)

**Date:** 2026-08-16
**Repo where the work happens:** https://github.com/AgentParadise/agentic-primitives
**Consumer:** syntropic137, per `docs/adrs/ADR-067-model-registry-and-cost-attribution.md`
**Status:** ready to start

> This spec lives in syntropic137 because the agentic-primitives submodule checkout is at a
> detached, dirty HEAD (`944e4b5`). Do not build from that checkout - clone or fetch fresh.

## Why

syn137 hardcodes a model pricing table that duplicates - badly - the registry
agentic-primitives already owns under ADR-018. syn137 will switch to generating its table
from this registry. Before it can, the registry needs four gaps closed and one artifact
published.

Everything below is additive. No existing consumer of `providers/models/` breaks.

## Current state (verified 2026-08-16)

- 20+ cards under `providers/models/{anthropic,openai,google}/`, one YAML per model
- `providers/models/<vendor>/config.yaml` maps aliases: `haiku -> claude-4-5-haiku`
- `providers/.schemas/model-config.schema.json` exists but requires
  `name`/`family`/`api`/`pricing.input`, while every card uses
  `full_name`/`api_name`/`pricing.input_per_1m_tokens`. **It validates zero cards.**
- `grep -rn "model-config.schema"` finds no CI job or test: **the schema is not enforced**
- No cache pricing on any card
- `claude-cli-version-check.yml` is a daily cron that npm-checks the pinned Claude CLI and
  files an issue when stale. This is the pattern to copy for models.

## Work items

> **Ordering note.** Item 0 comes first deliberately. This registry is itself already a
> generation stale (it knows the 4.5 family; reality is the Claude 5 family plus Haiku 4.5),
> and the syn137 table it was meant to replace is two generations stale. Hand-curation has
> failed twice. Backfilling cards without first automating discovery just resets the clock.

### 0. Automated model discovery (do this first)

A scheduled workflow, modelled on the existing `claude-cli-version-check.yml`:

1. Query each vendor's authoritative model list (Anthropic and OpenAI both expose a models
   endpoint; the published pricing page is the fallback).
2. Diff against `providers/models/<vendor>/`.
3. On any new, renamed, retired, or re-priced model, open a PR that scaffolds or updates
   the card from the fetched values.

Rules the job must obey:

- **Never invent a rate.** If a rate cannot be read from the source, write `null` and
  `is_placeholder: true`. The consumer treats a null rate as `unpriced` and a placeholder
  rate as `pricing_status: "placeholder"`. It must never emit a plausible-looking number.
- **Update `config.yaml` aliases too.** `haiku`/`sonnet`/`opus` must track the vendor's
  current model. A stale alias is how syn137 ended up over-charging `opus` by 3x.
- **Fail CI on staleness**: any card whose `verified_at` exceeds the threshold, or any
  vendor-listed model with no card.

This is the item that determines whether the registry is still accurate in six months.
Everything below is table stakes by comparison.

### 1. Add cache pricing to the card schema and every card

```yaml
pricing:
  input_per_1m_tokens: 1.00
  output_per_1m_tokens: 5.00
  cache_read_per_1m_tokens: 0.10          # NEW
  cache_creation_per_1m_tokens: 1.25      # NEW
  currency: "USD"
```

Non-negotiable for the consumer: in a measured codex run, `cache_read` was **159,744 of
178K tokens (89%)**. A card without these fields cannot price real traffic.

Where a vendor does not publish a cache rate, set the field to `null` and set
`is_placeholder: true` (see item 3) rather than guessing or omitting.

### 2. Make the schema match reality, and enforce it

Rewrite `providers/.schemas/model-config.schema.json` against the cards as actually
written (`id`, `full_name`, `api_name`, `alias`, `version`, `provider`, `status`,
`capabilities`, `performance`, `pricing`, ...). Then add a CI job that validates **every**
file under `providers/models/**/*.yaml` against it and fails the build on drift.

Without enforcement this is a folder of hand-edited YAML wearing a schema costume.

### 3. Add provenance so a guess cannot pose as a fact

```yaml
pricing:
  ...
  verified_at: "2026-08-16"
  source: "https://platform.claude.com/docs/en/about-claude/models/overview"
  is_placeholder: false
```

Required on every card. The consumer propagates `is_placeholder` into
`pricing_status: "placeholder"` so an estimated cost is never displayed with the same
confidence as a verified one.

Add a CI check that fails when any `verified_at` is older than N days (start with 120).
This replaces the current hand-written `Last updated: 2025-11-24` comment, which is
machine-unreadable and ~9 months stale.

### 4. Backfill the current model generation

The registry's newest Claude cards are the 4.5 family. Current reality is the **Claude 5
family (Opus 5, Sonnet 5, Fable 5) plus Haiku 4.5**, and **GPT-5.6** on the OpenAI side.

Add these via item 0's job wherever possible rather than by hand, so the rates come from
the vendor source with real `verified_at`/`source` provenance. Any card a human writes
from memory must be marked `is_placeholder: true` until confirmed against the vendor page.

Also repoint `config.yaml` `current_models` so `opus`/`sonnet`/`haiku` resolve to the
current generation.

### 4b. Add the codex models actually in use

`providers/models/openai/` currently has `gpt-codex` (= `gpt-5.1-codex`), `gpt-5.1`, `o1`.

Missing and required: **`gpt-5.6-sol`**, which is what a ChatGPT-account codex login
actually runs (`~/.codex/config.toml` -> `model = "gpt-5.6-sol"`).

Important constraint discovered while testing: under ChatGPT-account auth, `codex exec`
**rejects** `gpt-5.6` with "model not supported when using Codex with a ChatGPT account".
Cards should record which auth modes a model is usable under, so the consumer does not pin
a model the deployment cannot run:

```yaml
api:
  usable_with: ["chatgpt_account", "api_key"]   # or a subset
```

### 5. Publish `models.json` as a release artifact

Add a build step that flattens every card into a single versioned document:

```json
{
  "version": "models/v1.0.0",
  "generated_at": "2026-08-16T00:00:00Z",
  "models": [
    {
      "id": "claude-4-5-haiku",
      "api_name": "claude-haiku-4-5-20251001",
      "aliases": ["haiku", "claude-haiku"],
      "provider": "anthropic",
      "status": "current",
      "pricing": {
        "input_per_1m_tokens": 1.00,
        "output_per_1m_tokens": 5.00,
        "cache_read_per_1m_tokens": 0.10,
        "cache_creation_per_1m_tokens": 1.25,
        "currency": "USD",
        "verified_at": "2026-08-16",
        "source": "https://...",
        "is_placeholder": false
      }
    }
  ]
}
```

Attach it to a `models/vX.Y.Z` tag. AP already tags per component (`sdlc/v1.4.1`,
`observability/v0.2.2`) through `plugin-tag.yml`, so this reuses existing machinery rather
than adding a release process.

**Semver meaning for this artifact:** patch = a rate correction or provenance refresh;
minor = a new model card; major = a schema change consumers must adapt to.

### 6. Model-release watch cron

Copy `claude-cli-version-check.yml`. Daily, for each vendor: fetch the current model list,
diff against `providers/models/<vendor>/`, and on any difference open an issue - or better,
a PR with the new card scaffolded from the vendor's published values, `is_placeholder: true`
until a human confirms.

This is the item that removes the "I have to track every model release" burden. The
maintenance action becomes reviewing a PR.

## Acceptance

- [ ] Every card carries cache pricing (or explicit `null` + `is_placeholder: true`)
- [ ] Schema matches every card; CI fails on drift
- [ ] Every card carries `verified_at`, `source`, `is_placeholder`
- [ ] Staleness check fails on `verified_at` older than the threshold
- [ ] `gpt-5.6-sol` present, with auth-mode constraints recorded
- [ ] `models.json` published on a `models/vX.Y.Z` tag
- [ ] Watch cron opens an issue/PR on vendor model changes
- [ ] `providers/models/anthropic/UPDATE_GUIDE.md` updated for the new required fields

## Notes for the implementer

- The alias mapping in `config.yaml` is already correct (`haiku -> claude-4-5-haiku`).
  syn137 is the side that is wrong (it maps `haiku -> claude-3-5-haiku-20241022`, two
  generations stale). Do not "fix" the registry to match syn137.
- Keep `pricing` a nested object. The consumer maps it to a value object; a flat schema
  would leak into every generated line.
- Do not add cost *calculation* here. This repo publishes rates; syn137 computes money.
