# Agent: DORA four-keys snapshot

## Purpose

Compute deploy frequency, lead time for changes, change failure rate and time
to restore for a window, from GitHub alone, so trends can be compared over
time. Numbers here are proxies with stated definitions; report the definition
with the number. Reference: Forsgren, Humble, Kim, *Accelerate* (2018), and
https://dora.dev.

## Workflow

Set the window and repo once. Every command below was run against this repo on 2026-10-13.

```
R=syntropic137/syntropic137
SINCE=$(date -u -v-30d +%Y-%m-%d 2>/dev/null || date -u -d '30 days ago' +%Y-%m-%d)
```

1. **Deploy frequency** (stable releases; prereleases excluded because the owner does not use them as deploys):
   ```
   gh release list -R $R --limit 100 --json tagName,isPrerelease,publishedAt \
     --jq "[.[]|select(.isPrerelease|not)|select(.publishedAt>=\"$SINCE\")]|{releases:length, tags:map(.tagName)}"
   ```
   Test deploys (`just pit-stop`) leave no GitHub trace; take their count from the orchestrator scratchpad and report it separately.
2. **Lead time for changes**, PR open to merge on `main`:
   ```
   gh pr list -R $R --state merged --base main --search "merged:>=$SINCE" --limit 1000 --json createdAt,mergedAt \
     | jq '[.[]|((.mergedAt|fromdateiso8601)-(.createdAt|fromdateiso8601))/3600]|sort
           |{prs:length, median_h:.[length/2|floor], p90_h:.[(length*0.9)|floor]}'
   ```
   Merge to production: for each stable release, hours from the oldest PR merge it carries to `publishedAt`. Membership comes from git history, not timestamps: a release pins the commit it was cut from, which can predate approval while `main` moves on, so take the PRs from `git log --first-parent --merges vPREV..vCURRENT` (as `scripts/changelog.py` does) and use `publishedAt` only as the endpoint. Report both; the second is the one users feel.
3. **Change failure rate**, stable releases followed by a later stable release of the same minor (a patch fix), plus revert PRs:
   ```
   gh release list -R $R --limit 100 --json tagName,isPrerelease,publishedAt \
     --jq "[.[]|select(.isPrerelease|not)|select(.publishedAt>=\"$SINCE\")]" \
     | jq 'sort_by(.publishedAt) as $r | [ $r[] as $x | ($x.tagName|ltrimstr("v")|split(".")[0:2]) as $mm
           | {tag:$x.tagName, fixed_by:([$r[]|select(.publishedAt>$x.publishedAt)|select((.tagName|ltrimstr("v")|split(".")[0:2])==$mm)|.tagName]|first)} ]
           | {releases:length, failed:map(select(.fixed_by!=null)), rate:((map(select(.fixed_by!=null))|length)/(length|if .==0 then 1 else . end))}'
   gh pr list -R $R --state merged --search "revert in:title merged:>=$SINCE" --json number,title
   ```
   A patch release is a failure only if it fixed a defect in its predecessor; read its notes (`gh release view <tag>`) and drop planned patch releases from the count.
4. **Time to restore**:
   - `main` red to green (`ci.yml` push runs):
     ```
     gh run list -R $R --workflow ci.yml --branch main --event push --limit 300 --json conclusion,createdAt,updatedAt \
       --jq "[.[]|select(.createdAt>=\"$SINCE\")|select(.conclusion==\"success\" or .conclusion==\"failure\")]" \
       | jq 'sort_by(.createdAt) | reduce .[] as $r ({red:null,gaps:[]};
             if $r.conclusion=="failure" then (if .red==null then .red=$r.createdAt else . end)
             elif .red!=null then .gaps+=[(($r.updatedAt|fromdateiso8601)-(.red|fromdateiso8601))/3600] | .red=null else . end)
             | {incidents:(.gaps|length), median_h:(.gaps|sort|.[length/2|floor]), max_h:(.gaps|max), still_red_since:.red}'
     ```
   - Bad release to fix: hours between each failed release from step 3 and its `fixed_by` release's `publishedAt`.
   - Release pipeline failures: `gh run list -R $R --workflow release-create.yml --limit 20 --json conclusion,createdAt,databaseId`.
5. Compare with the previous snapshot if one exists (orchestrator scratchpad or a prior retro) and name the biggest mover.

## Output

| Key | Value | Definition used | Window |
|---|---|---|---|

Plus one line each: what moved most since the last snapshot, and which one number to improve next.

## Health check

Depends on: stable releases being the only GitHub Releases that mean "deployed to users"; `ci.yml` being the CI workflow on `main` pushes; `release-create.yml` being the release pipeline; tag format `vX.Y.Z`; `gh` JSON fields `createdAt`, `mergedAt`, `publishedAt`, `isPrerelease`, `conclusion`. `date -v` is BSD (macOS), `date -d` is GNU; the fallback covers both. If release or CI workflow names change, update the commands here.
