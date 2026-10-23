# PR lifecycle and triggers

## The lifecycle

| Stage | PR state | Who acts | What moves it on |
|---|---|---|---|
| issue prioritised | none | owner or triage | a dispatch, by hand or by trigger |
| implement | draft, opened by the implement agent right after its first push (`gh pr create --draft`); `finalize_pr` opens it if that failed | implement phase | the push |
| verify and fix | draft | verify, fix, re-verify phases | a certified verdict, or rounds exhausted |
| finalize | ready, or left draft with the blocker written down | `finalize_pr` | the certified verdict |
| second verification | ready | `sdlc-reverify-pr-v1` or a local verifier | certified on another model or context |
| merge | merged | orchestrator | CI green, both verifications, merge commit |
| release | released | owner gate | `devops` |

Draft means "agents are still working on this; reviewing it is wasted
effort". Ready means "verified and, as far as the workflow can tell,
mergeable". Keeping that contract is what lets reviewers, humans and triggers
trust the state without reading the history.

## Trigger design

A trigger should fire on a transition that changes what should happen next.
Firing on noise wastes runs, and two agents on one branch fight over it.

| Transition | Good trigger | Why |
|---|---|---|
| draft to ready | expensive gates, second verifier | the work now claims to be done |
| review submitted on a ready PR | `review-fix` | a human asked for change; drafts are excluded |
| CI failed on a ready PR | `self-healing` | the claim is now false |
| CI failed on a draft | none; the owning run handles it | the workflow that opened it still owns the branch |
| `/syn` comment | `comment-command` | explicit request |

State on 2026-10-21: triggers are effectively unused on the owner's
deployment: two rules ever, one active (`pull_request.opened` to
`sdlc-reverify-pr-v1`) and one deleted, both with zero fires
(`references/audit-2026-10-21.md`). So every run in the window was dispatched
by hand or by the orchestrator. Enable them one at a time, on the transitions above, and
measure each before adding the next.

Known gap (2026-10-21): the `self-healing` preset fires on any failed check of
any PR, drafts included (`packages/syn-domain/src/syn_domain/contexts/github/_shared/trigger_presets.py`).
The `check_run` payload carries no draft flag, so the fix needs a PR lookup or a
draft-aware condition, not one more equality check.

Common practice outside this repo points the same way: run cheap static gates
on drafts and expensive ones on `ready_for_review`, allow one self-heal in
flight per PR keyed on the head SHA, and hand off to a human after a small
attempt cap. These are practice, not studies; measure them here before
adopting the numbers.

## Measuring the lifecycle

Report delivery metrics split by agent PRs and human PRs: lead time, change
failure rate, rework, and reverts within 14 days. DORA 2025 found higher AI
adoption associated with both higher throughput and higher instability
(https://dora.dev/insights/balancing-ai-tensions/), so a rise in change failure
rate is a regression even when throughput rises.

## Limits

Every rule has `max_attempts`, `cooldown_seconds` and `daily_limit`. There is
no spend limit, so size them from the cost of one run. A blocked event is not
retried later. Before enabling a rule, ask: what is the worst day this rule can
have, and is that acceptable? Details and guards are in `github-triggers`.

## When to change the lifecycle

Treat a lifecycle or trigger change like a workflow change: state the gap
with numbers from trigger history and PR outcomes, change one thing, and
compare. A trigger that "feels too noisy" is a hypothesis until the history
shows fires per PR and how many led to a merged fix.
