# Prepare an existing PR's head for verification

$ARGUMENTS

The task above names a pull request that already exists. This workflow does
not write that change: an earlier run did, and then could not verify it (most
often its verify phase died on provider capacity). Your job is to hand the
next phase, `verify`, exactly what the `implement` phase hands it in
`sdlc-implement-v3`: a branch, a full commit SHA on it, and a report saying
what the change is supposed to do.

You do not review the change, and you do not fix it. Every phase gets its own
fresh workspace, so nothing you leave on this filesystem survives; only what you
push and what you write to `artifacts/output/` reach the next phase.

## First: which PR, and is it still open?

Find the PR number the task names (`#NNNN`, or a pull request URL). Then:

```
gh pr view <number> --json number,url,state,isDraft,headRefName,headRefOid,baseRefName,headRepositoryOwner,isCrossRepository,title,body
```

**Refuse, and verify nothing, when:**

- the task names no PR, or names more than one and does not say which to verify;
- `gh pr view` cannot find it;
- its `state` is `MERGED` or `CLOSED` - there is nothing left to certify, and a
  verdict on it would be posted on a thread nobody is acting on;
- `isCrossRepository` is true - the head lives in a fork this workspace cannot
  push to, so neither the merge below nor a fix round could ever land;
- `baseRefName` is not `main`.

A refusal is `TASK_RESULT success=false`, with `failure_reason: "task"`. Never
fall back to verifying `main` or the default branch: a run that certifies the
wrong tree is worse than one that stops, because it looks like proof.

## Check out the head and bring it up to current main

```
gh pr checkout <number>
git rev-parse HEAD                       # must equal headRefOid above
git fetch origin
git merge --no-edit origin/main
git submodule update --init --recursive
```

Paste the output of each. Never rebase and never force push: this repository
merges main into feature branches, in that direction, always.

**Why the merge.** The gates verify runs (`just preflight-agent` and the unit
suite) live in `main`'s justfile. A head that predates them is not verifiable,
and a verify phase that checks out such a head refuses it - on a change that
may well be correct.

- **The merge is clean** (or `Already up to date.`): push it with
  `git push origin HEAD:<headRefName>`, a plain fast-forward. The SHA you hand
  on is the new `git rev-parse HEAD`, read after the push from
  `git rev-parse origin/<headRefName>` - they must be equal.
- **The merge conflicts**: run `git merge --abort`, push nothing, and hand on
  the PR's own `headRefOid`. List every conflicted path in your report under
  `## Merge with main: CONFLICTED`. Do not resolve the conflict here: resolving
  it is a change to the PR, and a change made in this phase is one no verifier
  was told to look for. `verify` will find the head stale or failing, and the
  `fix` round that follows is where a conflict gets resolved.

## Describe the change

So the verifier knows what the change claims, collect:

```
gh pr diff <number> --name-only
git diff --stat origin/main...HEAD
gh pr view <number> --json body --jq .body
```

and, for each issue the PR body closes or references, `gh issue view <n>`.
The PR body is the brief this change was built against. When the task above
adds a brief of its own beyond naming the PR, that is the brief to verify
against as well; say which you used.

## Write to `artifacts/output/prepare.md`

**This phase declares a markdown output artifact, so a run that writes
nothing under `artifacts/output/` FAILS.** Write the file whatever the
outcome, including a refusal - a refusal is a deliverable and says why the run
stopped.

`verify` reads this file as the implementation report, so it must contain,
exactly and under these headings:

- `## PR` - the number and URL, and its draft state.
- `## Branch` - the head branch name, on its own line.
- `## Commit` - the FULL 40-character SHA `verify` must check out, on its own
  line, and whether it is the PR head as found or the merge you pushed.
- `## Merge with main` - `CLEAN` (with the pushed SHA), `ALREADY UP TO DATE`,
  or `CONFLICTED` (with every conflicted path).
- `## Diff summary` - the `--stat` output and the list of changed files.
- `## Brief` - the PR body verbatim, the referenced issues, and any brief the
  task added.

Write no verdict on the change itself. You have not reviewed it, and a report
that sounds like a review is one the verifier will be tempted to agree with.
