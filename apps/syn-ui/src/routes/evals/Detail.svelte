<!-- One eval. Boards: Eval · PhoneEval. Header, Trend, same case under other verifiers, Compare, Runs. -->
<script lang="ts">
  import { getEval, getEvalTrend, listEvalRuns, listEvals } from '@syn137/syn-ui-data'
  import { Callout, EmptyState, Pagination, Skeleton } from '@syn137/skyline-svelte-v5'
  import { PageHeader, VerdictBlock } from '@syn137/skyline-svelte-v5/patterns'
  import { formatCost, formatDateTime, formatDuration, formatRelativeTime } from '@syn137/skyline-core/format'
  import { normalizeVerdict } from '@syn137/skyline-core/patterns'
  import { agentOfModel, evalFigures, evidenceFallback, parseEvidence, runModels, runOutcome, sameCaseVerifiers, tagValue, variantPassed, variantStats, verdictWord } from '@syn137/skyline-core/screens/evals'
  import { isRunFinished } from '@syn137/syn-ui-data/live'
  import { resource } from '../../lib/load.svelte'
  import { setPage } from '../../lib/page.svelte'
  import { href } from '../../lib/router'
  import type { PageProps } from '../../lib/routes'
  import EvalTag from './EvalTag.svelte'
  import FlaskIcon from './FlaskIcon.svelte'
  import EvalTrend from './parts/EvalTrend.svelte'

  let { params }: PageProps = $props()

  const RUNS_PAGE = 20

  const live = { live: isRunFinished }
  const ev = resource((signal) => getEval(params.evalId ?? '', signal), live)
  let runsPage = $state(1)
  // A sibling link reuses this page: start its runs at page 1.
  let seenEval = ''
  $effect.pre(() => {
    const id = params.evalId ?? ''
    if (id !== seenEval) {
      seenEval = id
      runsPage = 1
    }
  })
  const runs = resource((signal) => {
    const page = runsPage
    return listEvalRuns(params.evalId ?? '', { page, page_size: RUNS_PAGE }, signal)
  }, live)
  const trend = resource((signal) => getEvalTrend(params.evalId ?? '', signal), live)
  const caseId = $derived(ev.data ? tagValue(ev.data.tags, 'case') : null)
  const siblingsRes = resource((signal) => {
    const c = caseId
    return c ? listEvals({ tag: `case:${c}`, page_size: 50 }, signal) : Promise.resolve(null)
  })

  $effect(() => {
    if (ev.data) setPage({ title: ev.data.name, crumbs: [{ label: 'Evals', href: '/evals' }, { label: ev.data.name }] })
  })

  const e = $derived(ev.data)
  const siblings = $derived(e && siblingsRes.data ? sameCaseVerifiers(e, siblingsRes.data.evals) : [])
  const figures = $derived(e ? evalFigures(e) : [])
  const runsPageCount = $derived(runs.data ? Math.max(1, Math.ceil(runs.data.total / RUNS_PAGE)) : 1)

  const errText = (x: unknown) => (x instanceof Error ? x.message : String(x))
  const agentOf = (models: readonly string[]) => agentOfModel(models[0])
  const tagHref = (t: string) => href(`/evals?tag=${encodeURIComponent(t)}`)
</script>

{#if ev.error && !e}
  <Callout tone="danger" title="Could not load this eval">{errText(ev.error)}</Callout>
  <p class="sky-eval__back"><a href={href('/evals')}>Back to evals</a></p>
{:else if !e}
  <section class="sky-eval__card" aria-busy="true" aria-label="Loading eval">
    <Skeleton variant="text" width="16rem" />
    <Skeleton variant="title" width="70%" />
    <Skeleton variant="text" lines={3} />
  </section>
  <section class="sky-eval__card" aria-hidden="true"><Skeleton variant="block" height="9rem" /></section>
{:else}
  <PageHeader kind="eval" eyebrow={e.eval_id} title={e.name} description={e.goal} {figures}>
    {#if e.frozen || e.archived}
      <div class="sky-eval__flags">
        {#if e.frozen}
          <span class="sky-eval__flag" data-tone="accent">
            <svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3.5" y="7.25" width="9" height="6" rx="1.5"></rect><path d="M5.5 7.25V5.25a2.5 2.5 0 0 1 5 0v2"></path></svg>
            Frozen
          </span>
        {/if}
        {#if e.archived}<span class="sky-eval__flag">Archived</span>{/if}
      </div>
    {/if}
    {#if e.baseline_repos.length > 0}
      <ul class="sky-eval__baseline" aria-label="Baseline">
        {#each e.baseline_repos as repo (repo.repository)}
          <li>
            <span class="sky-eval__dim">Baseline</span>
            <a href={`https://github.com/${repo.repository}/tree/${repo.commit_sha}`} target="_blank" rel="noopener noreferrer">{repo.repository}@{repo.commit_sha.slice(0, 12)}</a>
            <span class="sky-eval__dim sky-eval__wrap">({repo.requested_ref})</span>
          </li>
        {/each}
      </ul>
    {/if}
    {#if e.tags.length > 0}
      <div class="sky-eval__tags">
        {#each e.tags as t (t)}
          <a class="sky-eval__tag-link" href={tagHref(t)} title={`Evals tagged ${t}`}><EvalTag tag={t} /></a>
        {/each}
      </div>
    {/if}
  </PageHeader>

  <EvalTrend evalId={e.eval_id} evalName={e.name} rows={trend.data?.items ?? null} changes={trend.data?.definition_changes ?? []} error={trend.error} />

  {#if caseId}
    <section class="sky-eval__section" aria-labelledby="sky-eval-siblings">
      <div class="sky-eval__head">
        <h2 id="sky-eval-siblings">Same case, other verifiers</h2>
        <span>Evals that share the tag <code>case:{caseId}</code>: each verifier with its own latest verdict.</span>
      </div>
      {#if siblingsRes.error && !siblingsRes.data}
        <Callout tone="warning" title="Could not load the other verifiers">{errText(siblingsRes.error)}</Callout>
      {:else if !siblingsRes.data}
        <div class="sky-eval__sibs" aria-busy="true">
          {#each [0, 1, 2, 3] as i (i)}<Skeleton variant="block" height="9rem" />{/each}
        </div>
      {:else}
        <div class="sky-eval__sibs">
          {#each siblings as s (s.key)}
            {@const v = s.verdict}
            {@const models = s.models}
            {@const name = models.join(', ') || s.workflowId}
            {@const current = s.current}
            <a
              class="sky-eval__sib"
              href={href(`/evals/${encodeURIComponent(s.evalId)}`)}
              aria-current={current ? 'page' : undefined}
              aria-label={`${caseId} under ${name}: ${verdictWord(v)}${current ? ' (this eval)' : ''}`}
            >
              <VerdictBlock verdict={v} size={70} />
              <span class="sky-eval__model"><span class="sky-eval__dot" data-agent={agentOf(models)}></span>{name}</span>
              <span class="sky-eval__word" data-verdict={v}>{verdictWord(v)}{current ? ' · this eval' : ''}</span>
              <span class="sky-eval__meta">{s.avgCost ? `avg ${s.avgCost}` : '—'} · {formatRelativeTime(s.lastRunAt)}</span>
            </a>
          {/each}
        </div>
      {/if}
    </section>
  {/if}

  <section class="sky-eval__card sky-eval__compare" aria-labelledby="sky-eval-compare">
    <div class="sky-eval__head">
      <h2 id="sky-eval-compare">Compare</h2>
      <span>{e.run_count} {e.run_count === 1 ? 'run' : 'runs'} · {e.scored_count} scored · pass rate {e.pass_rate_display}. One row per workflow, version and model set.</span>
    </div>
    {#if (e.variants ?? []).length === 0}
      <EmptyState bare level={3} title="No variants yet" description="A variant appears once a run of this eval completes." />
    {:else}
      <div class="sky-eval__scroll">
        <table class="sky-eval__table" data-min="compare">
          <thead>
            <tr><th scope="col">Workflow · version · models</th><th scope="col" data-num="">Passed</th><th scope="col">Pass rate</th><th scope="col" data-num="">Median time</th><th scope="col" data-num="">Median cost</th><th scope="col" data-num="">Last run</th></tr>
          </thead>
          <tbody>
            {#each e.variants ?? [] as v (`${v.workflow_id}@${v.workflow_version}|${v.models.join(',')}`)}
              {@const p = variantPassed(v)}
              {@const st = variantStats(v)}
              <tr>
                <td>
                  <span class="sky-eval__mono-strong">{v.workflow_id}{v.workflow_version ? ` · ${v.workflow_version}` : ''}</span>
                  <span class="sky-eval__model"><span class="sky-eval__dot" data-agent={agentOf(v.models)}></span>{v.models.join(', ') || 'no model observed'}</span>
                </td>
                <td data-num="">{p.fraction}</td>
                <td>
                  <span class="sky-eval__rate">
                    <span class="sky-eval__bar" aria-hidden="true"><span style:width={`${p.fill ?? 0}%`}></span></span>
                    <span data-muted={p.fill === null ? '' : undefined}>{v.pass_rate_display}</span>
                  </span>
                </td>
                <td data-num="">{st.duration}</td>
                <td data-num="">{st.cost}</td>
                <td data-num="" class="sky-eval__muted" title={v.last_run_at ?? undefined}>{formatRelativeTime(v.last_run_at)}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    {/if}
  </section>

  <section class="sky-eval__card" aria-labelledby="sky-eval-runs">
    <div class="sky-eval__head">
      <h2 id="sky-eval-runs">Runs</h2>
      <span>Newest first. Each run is one execution.</span>
    </div>
    {#if runs.error && !runs.data}
      <Callout tone="danger" title="Could not load runs">{errText(runs.error)}</Callout>
    {:else if !runs.data}
      <Skeleton variant="text" lines={4} />
    {:else if runs.data.items.length === 0}
      <EmptyState bare level={3} title="No runs yet" description="Launch an execution into this eval and it shows up here.">
        {#snippet icon()}<FlaskIcon />{/snippet}
      </EmptyState>
    {:else}
      <ul class="sky-eval__runs" aria-busy={runs.loading}>
        {#each runs.data.items as run (run.execution_id)}
          {@const outcome = runOutcome(run)}
          {@const v = normalizeVerdict(run.verdict)}
          {@const phases = run.models ?? []}
          {@const facts = parseEvidence(run.evidence_excerpt)}
          {@const evidence = run.evidence_excerpt ?? (outcome.kind === 'run-failed' ? 'The execution failed before the verifier produced a report.' : evidenceFallback(v))}
          <li class="sky-eval__run">
            <div class="sky-eval__run-main">
              <a class="sky-eval__run-link" href={href(`/executions/${encodeURIComponent(run.execution_id)}`)}>{formatDateTime(run.started_at)}</a>
              <span class="sky-eval__mono-muted">{run.workflow_id ?? 'unknown workflow'}{run.workflow_version ? ` · ${run.workflow_version}` : ''}</span>
            </div>
            <div class="sky-eval__run-models">
              {#if phases.length === 0}
                <span class="sky-eval__dim">no model observed</span>
              {:else}
                {#each phases as m, i (`${m.phase_id}-${i}`)}
                  <span>{#if m.phase_id}<span class="sky-eval__dim">{m.phase_id}:</span> {/if}{m.model}</span>
                {/each}
              {/if}
              {#if phases.length === 0 && runModels(run).length}<span>{runModels(run).join(', ')}</span>{/if}
            </div>
            <div class="sky-eval__run-verdict">
              <span class="sky-eval__pill" data-verdict={outcome.verdict} data-outcome={outcome.kind}>{outcome.word}</span>
              {#if facts}
                <dl class="sky-eval__facts">
                  {#if facts.runStatus}<div><dt>Run status</dt><dd>{facts.runStatus}</dd></div>{/if}
                  {#if facts.reviewVerdict}<div><dt>Review verdict</dt><dd>{facts.reviewVerdict}{#if facts.reviewNeeds}<span class="sky-eval__dim"> (pass needs {facts.reviewNeeds})</span>{/if}</dd></div>{/if}
                  {#if facts.findings !== null}<div><dt>Blocking findings</dt><dd>{facts.findings}</dd></div>{/if}
                  {#if facts.expectedFile}<div><dt>Expected file</dt><dd class="sky-eval__path">{facts.expectedFile}</dd></div>{/if}
                </dl>
                <details class="sky-eval__raw">
                  <summary>Scorer evidence</summary>
                  <pre>{evidence}</pre>
                </details>
              {:else}
                <details class="sky-eval__evidence">
                  <summary><span class="sky-eval__clamp">{evidence}</span><span class="sky-eval__more" aria-hidden="true"></span></summary>
                </details>
              {/if}
              {#if run.scorer}<span class="sky-eval__mono-muted">{run.scorer}{run.scorer_version ? ` v${run.scorer_version}` : ''}{run.score !== null && run.score !== undefined ? ` · score ${run.score}` : ''}</span>{/if}
            </div>
            <dl class="sky-eval__run-figs">
              <div><dt>Cost</dt><dd>{run.total_cost_display ?? formatCost(run.total_cost_usd)}</dd></div>
              <div><dt>Duration</dt><dd class="sky-eval__muted">{run.duration_display ?? formatDuration(run.duration_seconds === null || run.duration_seconds === undefined ? null : run.duration_seconds * 1000)}</dd></div>
              <div><dt>Status</dt><dd class="sky-eval__muted">{run.status}</dd></div>
            </dl>
          </li>
        {/each}
      </ul>
      {#if runsPageCount > 1}
        <Pagination page={runsPage} pageCount={runsPageCount} summary={`${runs.data.total} runs`} aria-label="Runs pages" onPageChange={(p) => (runsPage = p)} />
      {/if}
    {/if}
  </section>
{/if}

<style>
  .sky-eval__back a,
  .sky-eval__baseline a {
    color: var(--ds-color-fg);
    text-decoration: underline;
    text-decoration-color: var(--sky-color-border-hover);
    text-underline-offset: 3px;
  }
  .sky-eval__back a:focus-visible,
  .sky-eval__baseline a:focus-visible,
  .sky-eval__tag-link:focus-visible,
  .sky-eval__sib:focus-visible,
  .sky-eval__run-link:focus-visible {
    outline: var(--sky-focus-ring-width) solid var(--sky-color-focus);
    outline-offset: var(--sky-focus-ring-offset);
  }
  .sky-eval__flags,
  .sky-eval__tags {
    display: flex;
    flex-wrap: wrap;
    gap: var(--ds-space-1-5);
    min-width: 0;
  }
  .sky-eval__flag {
    display: inline-flex;
    align-items: center;
    gap: var(--ds-space-1-5);
    height: 1.5rem;
    padding: 0 var(--ds-space-2-5);
    border-radius: var(--ds-radius-full);
    background: var(--sky-color-neutral-soft);
    color: var(--ds-color-text-muted);
    font-size: var(--ds-text-xs);
    font-weight: var(--ds-font-weight-semibold);
  }
  .sky-eval__flag[data-tone='accent'] {
    background: var(--sky-color-accent-soft);
    color: var(--sky-color-accent-soft-fg);
  }
  .sky-eval__baseline {
    margin: 0;
    padding: 0;
    list-style: none;
    font-family: var(--ds-font-mono);
    font-size: var(--ds-text-xs);
    line-height: var(--ds-line-height-normal);
    overflow-wrap: anywhere;
  }
  .sky-eval__tag-link {
    display: inline-flex;
    max-width: 100%;
    text-decoration: none;
    border-radius: var(--ds-radius-full);
  }
  .sky-eval__dim {
    color: var(--ds-color-text-subtle);
  }
  .sky-eval__muted {
    color: var(--ds-color-text-muted);
  }
  .sky-eval__wrap {
    overflow-wrap: anywhere;
  }
  .sky-eval__section {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-3-5);
    min-width: 0;
  }
  .sky-eval__head {
    display: flex;
    flex-wrap: wrap;
    align-items: baseline;
    gap: var(--ds-space-1) var(--ds-space-3);
  }
  .sky-eval__head h2 {
    margin: 0;
    font-size: var(--ds-text-xl);
    font-weight: var(--ds-font-weight-semibold);
    letter-spacing: var(--sky-tracking-title);
  }
  .sky-eval__head > span {
    font-size: var(--ds-text-sm);
    color: var(--ds-color-text-muted);
  }
  .sky-eval__head code {
    font-family: var(--ds-font-mono);
    font-size: var(--ds-text-xs);
    color: var(--sky-color-text-code);
    overflow-wrap: anywhere;
  }
  .sky-eval__card {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-4);
    min-width: 0;
    padding: var(--ds-space-4);
    border-radius: var(--sky-radius-card-lg);
    border: var(--ds-border-width) solid var(--ds-color-border);
    background: var(--ds-color-surface);
    box-shadow: var(--sky-shadow-raised);
  }
  .sky-eval__sibs {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: var(--ds-space-2-5);
  }
  .sky-eval__sib {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: var(--ds-space-1-5);
    min-width: 0;
    padding: var(--ds-space-3) var(--ds-space-2) var(--ds-space-3-5);
    border-radius: var(--sky-radius-xl);
    border: var(--ds-border-width) solid var(--ds-color-border);
    background: var(--ds-color-bg);
    color: var(--ds-color-fg);
    text-align: center;
    text-decoration: none;
  }
  .sky-eval__sib:hover {
    border-color: var(--sky-color-border-hover);
  }
  .sky-eval__sib[aria-current='page'] {
    border-color: var(--sky-color-accent-ring);
    background: var(--ds-color-overlay);
    box-shadow: var(--sky-shadow-selected);
  }
  .sky-eval__model {
    display: inline-flex;
    align-items: center;
    gap: var(--ds-space-1-5);
    min-width: 0;
    font-family: var(--ds-font-mono);
    font-size: var(--ds-text-xs);
    overflow-wrap: anywhere;
  }
  .sky-eval__dot {
    flex-shrink: 0;
    width: 7px;
    height: 7px;
    border-radius: 50%;
    background: var(--ds-color-text-subtle);
  }
  .sky-eval__dot[data-agent='claude'] {
    background: var(--sky-color-agent-claude);
  }
  .sky-eval__dot[data-agent='codex'] {
    background: var(--sky-color-agent-codex);
  }
  .sky-eval__word {
    font-size: var(--ds-text-xs);
    font-weight: var(--ds-font-weight-semibold);
  }
  .sky-eval__word[data-verdict='pass'] {
    color: var(--sky-color-accent-soft-fg);
  }
  .sky-eval__word[data-verdict='fail'] {
    color: var(--sky-color-danger-soft-fg);
  }
  .sky-eval__word[data-verdict='error'] {
    color: var(--sky-color-warning-soft-fg);
  }
  .sky-eval__word[data-verdict='unscored'] {
    color: var(--ds-color-text-muted);
  }
  .sky-eval__meta,
  .sky-eval__mono-muted {
    font-family: var(--ds-font-mono);
    font-size: var(--ds-text-xs);
    color: var(--ds-color-text-muted);
    overflow-wrap: anywhere;
  }
  .sky-eval__scroll {
    overflow-x: auto;
    min-width: 0;
  }
  .sky-eval__table {
    width: 100%;
    min-width: 35rem;
    border-collapse: collapse;
    font-size: var(--ds-text-sm);
  }
  .sky-eval__table[data-min='compare'] {
    min-width: 40rem;
  }
  .sky-eval__table th {
    padding: 0 var(--ds-space-2) var(--ds-space-2-5);
    border-bottom: var(--ds-border-width) solid var(--ds-color-border);
    font-family: var(--ds-font-mono);
    font-size: var(--sky-text-label);
    font-weight: var(--ds-font-weight-regular);
    letter-spacing: var(--sky-tracking-label);
    text-transform: uppercase;
    text-align: left;
    color: var(--ds-color-text-subtle);
  }
  .sky-eval__table td {
    padding: var(--ds-space-3) var(--ds-space-2);
    border-bottom: var(--ds-border-width) solid var(--sky-color-divider);
    vertical-align: middle;
  }
  .sky-eval__table tr:last-child td {
    border-bottom: 0;
  }
  .sky-eval__table td:first-child {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-1);
  }
  .sky-eval__table [data-num] {
    text-align: right;
    font-family: var(--ds-font-mono);
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
  }
  .sky-eval__mono-strong {
    font-family: var(--ds-font-mono);
    font-weight: var(--ds-font-weight-semibold);
    overflow-wrap: anywhere;
  }
  .sky-eval__rate {
    display: flex;
    align-items: center;
    gap: var(--ds-space-2-5);
    min-width: 8rem;
    font-family: var(--ds-font-mono);
    white-space: nowrap;
  }
  .sky-eval__rate [data-muted] {
    color: var(--ds-color-text-subtle);
  }
  .sky-eval__bar {
    flex-grow: 1;
    height: 8px;
    border-radius: 4px;
    background: var(--sky-color-track);
    overflow: hidden;
  }
  .sky-eval__bar span {
    display: block;
    height: 100%;
    border-radius: 4px;
    background: var(--ds-color-accent);
  }
  .sky-eval__runs {
    display: flex;
    flex-direction: column;
    margin: 0;
    padding: 0;
    list-style: none;
  }
  .sky-eval__run {
    display: grid;
    grid-template-columns: minmax(0, 1fr);
    gap: var(--ds-space-2-5);
    padding: var(--ds-space-3-5) 0;
    border-bottom: var(--ds-border-width) solid var(--sky-color-divider);
  }
  .sky-eval__run:last-child {
    border-bottom: 0;
  }
  .sky-eval__run-main,
  .sky-eval__run-models,
  .sky-eval__run-verdict {
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    gap: var(--ds-space-1);
    min-width: 0;
  }
  .sky-eval__run-models {
    font-family: var(--ds-font-mono);
    font-size: var(--ds-text-xs);
    overflow-wrap: anywhere;
  }
  .sky-eval__run-link {
    font-weight: var(--ds-font-weight-semibold);
    color: var(--ds-color-fg);
    text-decoration: none;
    border-radius: var(--ds-radius-xs);
  }
  .sky-eval__run-link:hover {
    color: var(--ds-color-accent-hover);
  }
  .sky-eval__pill {
    display: inline-flex;
    align-items: center;
    height: 1.5rem;
    padding: 0 var(--ds-space-2-5);
    border-radius: var(--ds-radius-full);
    font-size: var(--ds-text-xs);
    font-weight: var(--ds-font-weight-semibold);
    background: var(--sky-color-neutral-soft);
    color: var(--ds-color-text-muted);
  }
  .sky-eval__pill[data-verdict='pass'] {
    background: var(--sky-color-accent-soft);
    color: var(--sky-color-accent-soft-fg);
  }
  .sky-eval__pill[data-verdict='fail'] {
    background: var(--sky-color-danger-soft);
    color: var(--sky-color-danger-soft-fg);
  }
  .sky-eval__pill[data-verdict='error'] {
    background: var(--sky-color-warning-soft);
    color: var(--sky-color-warning-soft-fg);
  }
  .sky-eval__pill[data-outcome='run-failed'] {
    background: transparent;
    box-shadow: inset 0 0 0 var(--ds-border-width) var(--sky-color-border-strong);
  }
  .sky-eval__run-verdict {
    max-width: 100%;
  }
  .sky-eval__evidence,
  .sky-eval__raw,
  .sky-eval__facts {
    min-width: 0;
    max-width: 100%;
    font-size: var(--ds-text-sm);
    line-height: var(--ds-line-height-normal);
    color: var(--ds-color-text-muted);
    overflow-wrap: anywhere;
  }
  .sky-eval__evidence summary,
  .sky-eval__raw summary {
    cursor: pointer;
    list-style: none;
    border-radius: var(--ds-radius-xs);
  }
  .sky-eval__evidence summary::-webkit-details-marker,
  .sky-eval__raw summary::-webkit-details-marker {
    display: none;
  }
  .sky-eval__evidence summary:focus-visible,
  .sky-eval__raw summary:focus-visible {
    outline: var(--sky-focus-ring-width) solid var(--sky-color-focus);
    outline-offset: var(--sky-focus-ring-offset);
  }
  .sky-eval__clamp {
    display: -webkit-box;
    -webkit-box-orient: vertical;
    -webkit-line-clamp: 2;
    line-clamp: 2;
    overflow: hidden;
    white-space: pre-line;
  }
  .sky-eval__evidence[open] .sky-eval__clamp {
    display: block;
    -webkit-line-clamp: unset;
    line-clamp: none;
  }
  .sky-eval__more::before {
    content: 'Show all';
    font-size: var(--ds-text-xs);
    color: var(--ds-color-accent);
  }
  .sky-eval__evidence[open] .sky-eval__more::before {
    content: 'Show less';
  }
  .sky-eval__raw summary {
    font-size: var(--ds-text-xs);
    color: var(--ds-color-accent);
  }
  .sky-eval__raw pre {
    margin: var(--ds-space-1-5) 0 0;
    font-family: var(--ds-font-mono);
    font-size: var(--ds-text-xs);
    white-space: pre-wrap;
    overflow-wrap: anywhere;
  }
  .sky-eval__facts {
    display: grid;
    grid-template-columns: auto minmax(0, 1fr);
    gap: var(--ds-space-0-5) var(--ds-space-3);
    margin: 0;
  }
  .sky-eval__facts div {
    display: contents;
  }
  .sky-eval__facts dt {
    font-family: var(--ds-font-mono);
    font-size: var(--sky-text-label);
    letter-spacing: var(--sky-tracking-label);
    text-transform: uppercase;
    color: var(--ds-color-text-subtle);
    padding-top: 0.15em;
  }
  .sky-eval__facts dd {
    margin: 0;
    min-width: 0;
    color: var(--ds-color-fg);
  }
  .sky-eval__path {
    font-family: var(--ds-font-mono);
    font-size: var(--ds-text-xs);
  }
  .sky-eval__run-figs {
    display: flex;
    flex-wrap: wrap;
    gap: var(--ds-space-1) var(--ds-space-5);
    margin: 0;
  }
  .sky-eval__run-figs div {
    display: flex;
    gap: var(--ds-space-1-5);
    align-items: baseline;
  }
  .sky-eval__run-figs dt {
    font-family: var(--ds-font-mono);
    font-size: var(--sky-text-label);
    letter-spacing: var(--sky-tracking-label);
    text-transform: uppercase;
    color: var(--ds-color-text-subtle);
  }
  .sky-eval__run-figs dd {
    margin: 0;
    font-family: var(--ds-font-mono);
    font-size: var(--ds-text-sm);
    font-variant-numeric: tabular-nums;
  }
  @media (pointer: coarse) {
    .sky-eval__run-link,
    .sky-eval__tag-link {
      min-height: var(--sky-size-touch);
      display: inline-flex;
      align-items: center;
    }
  }
  @media (min-width: 48rem) {
    .sky-eval__card {
      padding: var(--ds-space-6);
    }
    .sky-eval__sibs {
      grid-template-columns: repeat(auto-fit, minmax(12.5rem, 1fr));
      gap: var(--ds-space-3);
    }
    .sky-eval__run {
      grid-template-columns: minmax(12rem, 1.3fr) minmax(9rem, 1fr) minmax(14rem, 1.6fr) auto;
      align-items: start;
      gap: var(--ds-space-4);
      padding: var(--ds-space-3-5) var(--ds-space-2);
    }
    .sky-eval__run-figs {
      flex-direction: column;
      align-items: flex-end;
      text-align: right;
    }
    .sky-eval__run-figs dt {
      display: none;
    }
  }
</style>
