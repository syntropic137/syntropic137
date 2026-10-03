# Gather the failure corpus

$ARGUMENTS

You have one job: pull every execution in the window above into local files, so
the phases after you analyse data rather than re-fetch it. Do not analyse
anything yet. Do not form a theory.

## Why this is its own phase

Analysis agents routinely spend their first minutes discovering they have no
route to the deployment, or re-fetching the same page four times with different
filters. Both are avoidable by pulling once, to disk, before anyone reasons.

The population is also the point. A retrospective reads failures **as a set**;
one failed execution is ordinary debugging and does not need this workflow. If
you cannot get the whole window, say how much you got and what is missing,
because every percentage the next phase computes depends on the denominator you
hand it.

## What to pull

The API is at `$SYN_API_URL` with Basic auth `admin:$SYN_API_PASSWORD`. If those
are not set, say so and stop - do not guess a host.

```
GET /api/v1/executions?page_size=100
    -> workflow_execution_id, workflow_id, status, total_cost_usd,
       total_tokens, duration_seconds, completed_phases, total_phases,
       error_message, started_at

GET /api/v1/executions/{id}
    -> phases[]: name, status, model, cost_usd, duration_seconds,
       error_message, artifact_id, operations[]
```

**Page properly.** `total` describes the collection; the rows describe one page.
A count taken from a page and reported as the system is the most common error in
this kind of work. State how many pages you fetched and whether you reached the
end of the window.

**Fetch the detail for every non-completed execution.** The list's
`error_message` is truncated and the useful part - which phase, which command,
which exit code - is often past the cut. The next phase cannot classify what it
cannot read.

## Write to `artifacts/output/gather.md`

**This phase declares a markdown output artifact, so a run that writes nothing
under `artifacts/output/` FAILS.** Write the file before you finish.

Also write the raw data to files the later phases can read directly, and name
those paths in your artifact:

- `artifacts/output/executions.json` - the full list
- `artifacts/output/failures/<exec-id>.json` - one per non-completed execution

The artifact itself is short:

1. **The window** - exact start and end, in UTC, and how you bounded it.
2. **The denominator** - how many executions, how many completed, how many
   failed or cancelled, how many still running. Running ones are excluded from
   rates and must be counted anyway, because a reader needs to know they exist.
3. **Total spend**, and spend split by terminal status.
4. **What you could not get**, explicitly. A partial corpus is usable; a partial
   corpus described as complete is not.
5. **The file paths** you wrote, so the next phase reads rather than re-fetches.

Do not classify causes. Do not rank anything. The next phase does that, and it
does it better if you have not already told it what to think.
