# verifier-seed-v1: does verification block the bug and certify the clean change? (#967)

`suite.yaml` says what the suite measures, which verifiers it runs under, and
the history of every version. `scripts/eval_suite.py` checks, launches and
scores it:

```
uv run python scripts/eval_suite.py check   # git only: every pin, fix and control re-read
```

This file holds what `suite.yaml` cannot: how a case is chosen.

## Defect cases

A defect case is mined from a merged fix. The pin is the first fix commit's
first parent, so the bug is present and nothing of the fix is; `check` refuses
any other pin. The expected files are ones the fix changed, and a defect that
only shows at runtime is not a case.

## Clean controls

A clean control is a merged PR head the verifier must certify. It is only
worth anything if it really is clean: a control that carries a defect turns a
correct block into a "false block", and punishes exactly the verifier that
found it. So a control must be hard to get wrong. From v5 a control is chosen
by this rule:

1. **It is a mainline merge of a PR head.** `commit` is the merge's second
   parent, and the merge is on `clean_through`'s first-parent chain.
   *Enforced by `check`.*
2. **No later fix PR refers to it.** No commit between the merge and
   `clean_through` is a fix or revert whose message names `#<source_pr>` or
   one of its SHAs. *Enforced by `check`.* A fix that refers to the control's
   code without naming its PR is not caught by this, which is what rule 3 is
   for. Also search the issues and fix PRs by hand for the files and
   functions the control changed.
3. **What it changed stayed untouched for 30 days.** `clean_through` is at
   least 30 days after the merge, and no mainline commit in those 30 days
   touches a Python function the PR changed. A function is followed by its
   qualified name (`Class.method`), so moving it does not hide a later edit.
   *Enforced by `check` for Python; controls added before v5
   (`added_in` < 5) have their quiet days so far checked, and the rest as
   `clean_through` advances.* A non-Python change cannot be followed by
   function here: read its later history by hand before choosing it.

Rule 3 exists because rule 2 alone let two bad controls in. Both v3 controls
that v5 retired had later commits rewriting the very functions they added
(`check` now reports six such commits for one and two for the other), and none of
those commits named the control's PR.

### A clean control both strong verifiers block is a candidate defect, not a false positive - investigate before scoring

Opus 5.5 (opus-5-5) and GPT-6.1 Sol (gpt-6.1-sol) independently blocked
`clean-redis-signal-queue-fail-open` and `clean-github-token-installation-routing`,
each naming the same defect. Both were real:

| Control | What the verifiers found | Outcome |
|---|---|---|
| `clean-redis-signal-queue-fail-open` (PR #1083) | `resilient_redis_client` retries GETDEL and SET NX on timeout; neither is idempotent, so a retried signal read loses the signal and a retried dedup claim reports a first delivery as a duplicate | Issue #1756, fixed by #1757. Retired; the defect is now `redis-retry-non-idempotent` |
| `clean-github-token-installation-routing` (PR #1130) | The first owning repo's installation token is used for the whole workspace, so another repo under a different installation gets the wrong token | Moved, not fixed, by ca367a88b (PR #1448) into `setup_phase_secrets._gh_token_for_repo_under_work`, still on main. Retired; no fix exists to cut a defect case from |

So when two strong verifiers block a control and name the same thing, do not
score it as a false block. Read the finding against the code first. If it
holds, retire the control and, once a fix exists, add the defect as a case.

## Retiring a case

Never re-polarise or delete a case that a history version holds: its runs
score against the case as it was. Set `retired:` to why, and in which version.
A retired case is not part of the current version and is never launched;
every history version that held it still scores it. `check` refuses a retired
case that no history version holds: delete that one instead.
