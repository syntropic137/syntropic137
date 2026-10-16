# Spike: does a workflow dispatch return its run, and how does `created` filter runs? (2026-10-16)

PR 1 of `docs/plans/20261015_platform-dispatched-evidence.md` (§A.15, branch
`docs/runtime-research-20261012`) owes two answers that §A.5's attempt
protocol depends on:

1. Does `POST /repos/{o}/{r}/actions/workflows/{id}/dispatches` return the run
   it created? This decides whether `dispatch(attempt)` can return
   `Accepted(run_id)` or always `Accepted(None)`.
2. How does the `created` filter on
   `GET /repos/{o}/{r}/actions/workflows/{id}/runs` behave? §A.5 step 2
   (`find_run`) adopts an attempt's run by listing `workflow_dispatch` runs
   with `created >= started_at - 2 min`.

Question 2 was answered live against this repository's
`mutation-evidence.yml` (workflow id `384882928`). Question 1 is answered
from GitHub's published REST description. **It has not been observed live**,
because no credential available to a workspace agent can dispatch (see
"Prerequisite for the live dispatch" below).

## 1. Dispatch returns its run only when asked

Source: `github/rest-api-description`,
`descriptions/api.github.com/api.github.com.json` at commit
`51a4657888cc1db93d8bd68086d117909fd8221c` (2026-10-16T01:02:26Z), file
sha256 `65ca6210f72021d07e4608fc26787c8132d77f8f3a475d8c065f0d7f5f02f6dc`,
operation `POST /repos/{owner}/{repo}/actions/workflows/{workflow_id}/dispatches`:

- The request body takes `ref` (required), `inputs` (at most 25 properties)
  and a boolean **`return_run_details`**: "Whether the response should
  include the workflow run ID and URLs."
- **`204`**: "Empty response when `return_run_details` parameter is `false`."
  This is the default and what `gh workflow run` and `justfile` dispatches
  get today: no run id.
- **`200`**: "Response including the workflow run ID and URLs when
  `return_run_details` parameter is `true`", schema
  `workflow-dispatch-response`, all three fields required:
  `{"workflow_run_id": 1, "run_url": "https://api.github.com/repos/o/r/actions/runs/1", "html_url": "https://github.com/o/r/actions/runs/1"}`.
- `x-github.enabledForGitHubApps: true`, `githubCloudOnly: false`.

**For §A.5:** the adapter sends `return_run_details: true`, and a `200` with
a `workflow_run_id` is `Accepted(run_id)`. `Accepted(None)` stays in the
port: a `204` (an API version or GHES release that ignores the flag), or a
`200` whose body does not parse, still dispatched and must be adopted
through `find_run`. A timeout or 5xx after the POST is `Ambiguous`, as
planned. A run id from the response never makes `find_run` unnecessary.

Reproduce:

```bash
gh api -H "Accept: application/vnd.github.raw" \
  repos/github/rest-api-description/contents/descriptions/api.github.com/api.github.com.json > api.json
python3 -c "import json; d=json.load(open('api.json')); \
op=d['paths']['/repos/{owner}/{repo}/actions/workflows/{workflow_id}/dispatches']['post']; \
print(json.dumps(op['responses'], indent=1)); \
print(json.dumps(d['components']['schemas']['workflow-dispatch-response'], indent=1))"
```

### Prerequisite for the live dispatch

The workspace installation token used for this spike reports
`{"admin":false,"maintain":false,"pull":false,"push":false,"triage":false}`
on `GET /repos/syntropic137/syntropic137` and has no `actions: write`. The
plan only grants `Actions: Read and write` to the App in PR 7 (DevOps lane),
after PR 4. A real dispatch also starts a real, billed CI run. So the live
check belongs to a credential that may dispatch (an owner's `gh`, or the App
after PR 7), and it is part of PR 6's adapter acceptance:

```bash
gh api -X POST repos/syntropic137/syntropic137/actions/workflows/mutation-evidence.yml/dispatches \
  -f ref=main -F return_run_details=true \
  -f 'inputs[pr]=<n>' -f 'inputs[tests]=<node id>' -f 'inputs[dispatch_id]=spike-1'
# expect HTTP 200 and workflow_run_id; then
gh api repos/syntropic137/syntropic137/actions/runs/<workflow_run_id> --jq .display_title
# expect "Mutation evidence for PR #<n> spike-1"
```

Until that runs, "dispatch returns its run id" is GitHub's documented
contract, not an observation.

## 2. The `created` filter, observed

All requests on 2026-10-16 against
`repos/syntropic137/syntropic137/actions/workflows/384882928/runs` with
`event=workflow_dispatch`, read-only (`actions: read`). The runs involved:

| run id | `created_at` | `display_title` |
|---|---|---|
| 38848185421 | 2026-10-16T03:58:27Z | Mutation evidence for PR #1985 orch-1985 |
| 38837975376 | 2026-10-16T01:58:22Z | Mutation evidence for PR #1981 orch-1981 |
| 38738249398 | 2026-10-15T12:54:18Z | Mutation evidence for PR #1975 u8b6b |
| 38737631268 | 2026-10-15T12:49:41Z | Mutation evidence for PR #1975 i8b6 |
| 38737551415 | 2026-10-15T12:49:04Z | Mutation evidence for PR #1975 u8b6 |

| `created=` | `total_count` | runs returned | finding |
|---|---:|---|---|
| `>=2026-10-15T12:49:41Z` | 4 | ...85421 ... 31268 | `>=` is inclusive, to the second |
| `>2026-10-15T12:49:41Z` | 3 | ...85421 ... 49398 | `>` is exclusive |
| `2026-10-15T12:49:04Z..2026-10-15T12:49:41Z` | 2 | 31268, 51415 | `a..b` is inclusive at both ends |
| `>=2026-10-15T14:49:41+02:00` | 4 | same as the `Z` query | offsets are honoured |
| `>=2026-10-15T12:49` | 5 | includes 12:49:04 | minute precision truncates |
| `>=2026-10-16` | 2 | the two runs on 10-16 | date-only works (UTC) |
| `>=yesterday` | 0 | none, **HTTP 200** | a malformed bound is not an error |
| `>=2026-10-15T25:00:00Z` | 0 | none, **HTTP 200** | an impossible time is not an error |

Other observations:

- Runs come back newest first by `created_at`.
- With a filter, `total_count` counts the filtered set, and pagination uses a
  `Link` header with `prev`, `next`, `last` and `first` (`per_page=2&page=2`
  over `created=>=2026-10-15T00:00:00Z` returned `total_count: 17` and
  `rel="last"` at page 9).
- The workflow's `run-name` puts `dispatch_id` in both `name` and
  `display_title` (`Mutation evidence for PR #${{ inputs.pr }} ${{ inputs.dispatch_id }}`),
  so §A.5's "match on `dispatch_id` in the run name" works on list results
  with no per-run fetch.
- The published description says this endpoint "will return up to 1,000
  results for each search" when `created`, `event` and similar filters are
  used. A two-minute window never approaches that.

**For §A.5:**

- Format the bound as a full UTC timestamp to the second (`%Y-%m-%dT%H:%M:%SZ`)
  and use `>=`. It is inclusive, so a run created in the bound's own second is
  found.
- **A malformed `created` value silently returns zero runs with HTTP 200.**
  Read naively, that is "no run exists", which is the answer that makes the
  handler start a new attempt and duplicate a dispatch. The adapter must build
  the bound from a `datetime`, never pass through a string, and a test must
  pin the exact query string it sends.
- Because results are newest first and filtered by the bound, paging until
  there is no `next` link and stopping at the first page that predates the
  bound are the same stop condition here. Keep the predates check anyway: it
  costs nothing and survives an API that ignores the filter.

Reproduce (any `actions: read` token):

```bash
W=repos/syntropic137/syntropic137/actions/workflows/384882928/runs
for c in '>=2026-10-15T12:49:41Z' '>2026-10-15T12:49:41Z' \
         '2026-10-15T12:49:04Z..2026-10-15T12:49:41Z' '>=2026-10-15T14:49:41+02:00' \
         '>=2026-10-15T12:49' '>=2026-10-16' '>=yesterday'; do
  gh api -X GET "$W" -f event=workflow_dispatch -f "created=$c" \
    --jq "\"$c total=\(.total_count) \([.workflow_runs[]|.id]|join(\" \"))\""
done
gh api -i -X GET "$W" -f event=workflow_dispatch -f 'created=>=2026-10-15T00:00:00Z' \
  -f per_page=2 -f page=2 | grep -i '^link:'
```

Open-ended (`>=`, `>`) queries gain rows as more evidence runs are
dispatched; the closed range and the five runs above do not change.
