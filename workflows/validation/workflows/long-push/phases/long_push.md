# Push and use gh after the 60-minute token TTL (#725)

$ARGUMENTS

You are a validation probe. Follow these steps exactly, in order, and do nothing else.

The repository is cloned under `/workspace/repos/`. `cd` into it (there is exactly one).

## 1. Before the wait

Run and record the output of:

```
date -u +%FT%TZ
gh api repos/$(gh repo view --json nameWithOwner -q .nameWithOwner) --jq .full_name
```

## 2. Wait 72 minutes

Run `sleep 540` EIGHT times, as eight separate Bash calls, then `date -u +%FT%TZ`.
Do not shorten, skip, or combine them. The wait is the whole point of this test:
the credential the workspace started with expires at 60 minutes.

## 3. After the wait: push and use gh

```
B="syn-validate/long-push-$(date -u +%Y%m%d%H%M%S)"
git checkout -b "$B"
git commit --allow-empty -m "chore: #725 long-push validation (safe to delete)"
git push origin "$B"
gh api "repos/$(gh repo view --json nameWithOwner -q .nameWithOwner)/branches/$B" --jq .name
git push origin --delete "$B"
git checkout -
git branch -D "$B"
```

Run each command separately and capture its exact output. Do not retry a failed
push and do not work around a failure: a failure here is the result we are testing for.

## 4. Report

Write `artifacts/output/long_push.md` with exactly these lines, then print them:

```
STARTED: <timestamp from step 1>
PUSHED_AT: <timestamp after the wait>
GH_BEFORE: <ok or the error text>
PUSH: <ok or the exact error text>
GH_AFTER: <ok or the exact error text>
CLEANUP: <ok or the error text>
```
