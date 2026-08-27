# gpt-5.6-sol rate history, as this platform applied it

Reconstructed 2026-08-27 from `git log` over
`packages/syn-shared/src/syn_shared/pricing/__init__.py`.

**This is what Syntropic137 charged its own records, not what OpenAI charged.**
Two of the three eras were wrong. The distinction matters: a stored cost from
era 1 or 2 is not a historical fact to preserve, it is an error to correct.

| Effective from | Commit | Input | Output | Cached in | Cache write | Status |
|---|---|---|---|---|---|---|
| 2026-07-27 15:52 PDT | `ff902963` | $15.00 | $60.00 | $1.50 | (none) | **Overstated** |
| 2026-08-16 21:57 PDT | `f08d1f19` | $5.00 | $30.00 | $0.50 | $6.25 | **Overstated** |
| 2026-08-26 16:21 PDT | `d4638d71` | $4.00 | $20.00 | $0.40 | $5.00 | Correct |

Machine-readable: [`gpt-5.6-sol-rate-history.json`](gpt-5.6-sol-rate-history.json)

## Why this file exists

A codex session's cost is **frozen at write time**.
`CodexStreamProcessor._estimate_cost` prices the run when it completes, and
`session_cost/timescale_query.py:142-144` returns that stored value verbatim
whenever it is present, without consulting the rate table:

```python
sdk_cost = exec_result.get("sdk_cost") if exec_result else None
if sdk_cost is not None:
    return Decimal(str(sdk_cost))
```

So correcting the rate table does **not** reach any completed session. Rows
written during eras 1 and 2 still serve their overstated figure and always will.

The rate that produced each row is recorded nowhere. It exists only as the
combination of the row's timestamp and this history. **Any `UPDATE` that
overwrites `total_cost_usd` before this mapping is captured destroys the only
evidence of what was originally reported**, which is why this file is written
before any backfill runs rather than as part of one.

## What each era was

**Era 1, $15/$60.** An unverified `TODO(#780)` placeholder. Never checked
against a vendor page.

**Era 2, $5/$30.** Recorded as "verified against the OpenAI pricing page and
the OpenRouter models API". It matches **no gpt-5.6 tier**. It is an exact
match for OpenAI's `chat-latest` ($5.00 in / $0.50 cached / $30.00 out), the
ChatGPT product rather than the API model. The entry's own comment described
Sol as "the model a ChatGPT-account codex login actually runs", so pricing the
ChatGPT product was a reasonable-looking mistake, and the `$6.25` cache-write
figure was invented since `chat-latest` publishes none.

**Era 3, $4/$20.** Published Standard short-context rates from
<https://developers.openai.com/api/docs/pricing>, transcribed field by field and
pinned by `packages/syn-shared/tests/test_openai_published_rates.py`.

## Using this for a backfill

Codex rows are correctable. The rate that priced them came from this table, so
`row.time` plus this history reconstructs it exactly, and the corrected figure
is recomputable from the stored token counts.

Claude rows are **not** correctable. Their cost came from Anthropic's bundled
table inside the CLI at an unrecorded version, not from this repo. Recomputing
them at any rate replaces one number with a differently-derived one and calls it
a correction. Leave them alone and label them.

A backfill must be **additive**: keep `total_cost_usd` as recorded, add the
corrected value beside it with a status field. Both questions then stay
answerable, "what did we report at the time" and "what did it actually cost".

## Caveat this table does not capture

`ModelPricing` has no service tier and no context tier, while OpenAI publishes
four service tiers and two context tiers. Across those, Sol's output rate spans
$10.00 to $60.00. Every era above is the Standard short-context assumption. A
long-context run in any era is under-priced by a factor this history cannot
express, and closing that is part of ADR-067 phase 2.
