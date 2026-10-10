<!--
  One trigger, read as a Rule Sentence (Triggers board, right column; on a
  phone it opens in place under its rule). Readable / JSON, Pause or Resume,
  Delete behind an Alert Dialog, and the firing log.
-->
<script lang="ts">
  import { deleteTrigger, getTrigger, getTriggerHistory, updateTrigger } from '@syn137/syn-ui-data'
  import { AlertDialog, Button, Callout, Skeleton, ToggleGroup } from '@syn137/skyline-svelte-v5'
  import { RuleSentence, StatusBadge } from '@syn137/skyline-svelte-v5/patterns'
  import { formatCostPrecise, formatRelativeTime, shortId } from '@syn137/skyline-core/format'
  import { buildRuleClauses } from '@syn137/skyline-core/patterns'
  import { normalizeConditions, triggerLogLine, triggerRuleInput, triggerTitle } from '@syn137/skyline-core/screens/triggers'
  import { isRunEvent } from '@syn137/syn-ui-data/live'
  import { resource } from '../../lib/load.svelte'
  import { setPage } from '../../lib/page.svelte'
  import { href, router } from '../../lib/router'

  let {
    triggerId,
    onchanged,
    setCrumbs = false,
  }: {
    triggerId: string
    /** Called after pause/resume/delete so the list refreshes. */
    onchanged?: () => void
    /** Own the breadcrumb trail (the /triggers/:id route). */
    setCrumbs?: boolean
  } = $props()

  const trig = resource((signal) => getTrigger(triggerId, signal), { live: isRunEvent })
  const hist = resource((signal) => getTriggerHistory(triggerId, 20, signal).catch(() => ({ trigger_id: triggerId, entries: [] })), {
    live: isRunEvent,
  })
  const t = $derived(trig.data?.trigger_id === triggerId ? trig.data : undefined)
  const entries = $derived(hist.data?.entries ?? [])

  $effect(() => {
    if (setCrumbs && t) setPage({ title: triggerTitle(t), crumbs: [{ label: 'Triggers', href: '/triggers' }, { label: triggerTitle(t) }] })
  })

  let view = $state<string[]>(['readable'])
  const clauses = $derived.by(() => {
    if (!t) return []
    const input = triggerRuleInput(t, triggerLogLine(t.fire_count, entries.length))
    input.workflowHref = href(`/workflows/${encodeURIComponent(t.workflow_id)}`)
    return buildRuleClauses(input)
  })
  const blocks = $derived(
    t
      ? [
          { title: 'Conditions', code: JSON.stringify(normalizeConditions(t.conditions), null, 2) },
          { title: 'Input mapping', code: JSON.stringify(t.input_mapping ?? {}, null, 2) },
          { title: 'Config', code: JSON.stringify(t.config ?? {}, null, 2) },
        ]
      : [],
  )

  let busy = $state(false)
  let actionError = $state<string | null>(null)
  let confirmOpen = $state(false)

  async function toggle() {
    if (!t) return
    busy = true
    actionError = null
    try {
      await updateTrigger(t.trigger_id, t.status === 'active' ? 'pause' : 'resume')
      trig.refresh()
      onchanged?.()
    } catch (e) {
      actionError = e instanceof Error ? e.message : 'The server refused the change.'
    } finally {
      busy = false
    }
  }

  async function remove() {
    if (!t) return
    await deleteTrigger(t.trigger_id)
    onchanged?.()
    router.navigate('/triggers')
  }

  const errorText = $derived(trig.error instanceof Error ? trig.error.message : 'The server did not answer.')
</script>

{#snippet acts()}
  {#if t && t.status !== 'deleted'}
    <Button size="sm" loading={busy} onclick={toggle}>
      {#snippet icon()}
        {#if t?.status === 'active'}
          <svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M5.5 3.5v9M10.5 3.5v9"></path></svg>
        {:else}
          <svg width="12" height="12" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true"><path d="M5 3.25v9.5L12.5 8z"></path></svg>
        {/if}
      {/snippet}
      {t.status === 'active' ? 'Pause' : 'Resume'}
    </Button>
    <Button size="sm" tone="danger" aria-label="Delete trigger" onclick={() => (confirmOpen = true)}>
      {#snippet icon()}
        <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M2.75 4.25h10.5M6.25 4.25V2.75h3.5v1.5M4.25 4.25l.6 9h6.3l.6-9"></path></svg>
      {/snippet}
    </Button>
  {/if}
{/snippet}

<section class="sky-trigger" aria-label="Trigger detail" aria-busy={!t}>
  {#if trig.error && !t}
    <Callout tone="danger" title="Couldn't load this trigger." role="alert">
      {errorText}
      {#snippet action()}<Button size="sm" onclick={() => trig.refresh()}>Retry</Button>{/snippet}
    </Callout>
  {:else if !t}
    <Skeleton lines={6} label="Loading trigger" />
  {:else}
    <header class="sky-trigger__head">
      <div class="sky-trigger__name">
        <div class="sky-trigger__meta">
          <span class="sky-trigger__state" data-state={t.status}><span class="sky-trigger__dot" aria-hidden="true"></span>{t.status === 'active' ? 'Active' : t.status === 'paused' ? 'Paused' : t.status}</span>
          <span class="sky-trigger__id">{t.trigger_id}</span>
        </div>
        <h2 class="sky-trigger__title">
          <span class="sky-trigger__event">{t.event}</span>
          {#if t.workflow_name}<span class="sky-trigger__arrow" aria-hidden="true">→</span><span>{t.workflow_name}</span>{/if}
        </h2>
        {#if t.name && t.workflow_name}<p class="sky-trigger__sub">{t.name} · created by {t.created_by}</p>{/if}
      </div>
      <div class="sky-trigger__tools">
        <ToggleGroup
          type="single"
          variant="segmented"
          aria-label="View"
          bind:value={view}
          items={[
            { value: 'readable', label: 'Readable' },
            { value: 'json', label: 'JSON' },
          ]}
        />
        <span class="sky-trigger__acts" data-at="head">{@render acts()}</span>
      </div>
    </header>

    {#if actionError}
      <Callout tone="danger" title="That didn't work." role="alert">{actionError}</Callout>
    {/if}

    {#if view[0] === 'json'}
      <div class="sky-trigger__json">
        {#each blocks as b (b.title)}
          <div class="sky-trigger__block">
            <span class="sky-trigger__label">{b.title}</span>
            <pre>{b.code}</pre>
          </div>
        {/each}
      </div>
    {:else}
      <RuleSentence {clauses} size="full" />
    {/if}

    {#if entries.length}
      <ol class="sky-trigger__log" aria-label="Firing history">
        {#each entries as e, i (e.webhook_delivery_id ?? e.execution_id ?? i)}
          <li class="sky-trigger__fire">
            <StatusBadge status={e.status ?? 'unknown'} shape="glyph" />
            <span class="sky-trigger__fire-main">
              <span class="sky-trigger__fire-event">{e.event_type ?? 'unknown event'}</span>
              <span class="sky-trigger__fire-meta">
                {#if e.fired_at}<span>{formatRelativeTime(e.fired_at)}</span>{/if}
                {#if e.pr_number != null}<span>PR #{e.pr_number}</span>{/if}
                {#if e.cost_usd != null}<span>{formatCostPrecise(e.cost_usd)}</span>{/if}
              </span>
            </span>
            {#if e.execution_id}
              <a class="sky-trigger__fire-link" href={href(`/executions/${encodeURIComponent(e.execution_id)}`)}>Execution <span>{shortId(e.execution_id)}</span></a>
            {/if}
          </li>
        {/each}
      </ol>
    {/if}

    <!-- The phone board puts Pause and Delete at the foot of the opened rule. -->
    <div class="sky-trigger__acts" data-at="foot">{@render acts()}</div>

    <AlertDialog
      bind:open={confirmOpen}
      title="Delete this trigger?"
      description={`${triggerTitle(t)} stops firing on ${t.repository}. Past executions stay. This can't be undone.`}
      confirmLabel="Delete trigger"
      onConfirm={remove}
    />
  {/if}
</section>

<style>
  .sky-trigger {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-5);
    min-width: 0;
  }
  .sky-trigger__head {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-4);
  }
  .sky-trigger__name {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-2);
    min-width: 0;
  }
  .sky-trigger__meta {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--ds-space-2-5);
  }
  .sky-trigger__state {
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
  .sky-trigger__state[data-state='active'] {
    background: var(--sky-color-accent-soft);
    color: var(--sky-color-accent-soft-fg);
  }
  .sky-trigger__state[data-state='paused'] {
    background: var(--sky-color-warning-soft);
    color: var(--sky-color-warning-soft-fg);
  }
  .sky-trigger__dot {
    width: 6px;
    height: 6px;
    border-radius: var(--ds-radius-full);
    background: currentColor;
  }
  .sky-trigger__id {
    font-family: var(--ds-font-mono);
    font-size: var(--ds-text-xs);
    color: var(--ds-color-text-subtle);
  }
  .sky-trigger__title {
    display: flex;
    flex-wrap: wrap;
    align-items: baseline;
    gap: var(--ds-space-2);
    margin: 0;
    font-size: var(--ds-text-xl);
    font-weight: var(--ds-font-weight-semibold);
    letter-spacing: var(--sky-tracking-title);
    overflow-wrap: anywhere;
    min-width: 0;
  }
  .sky-trigger__event {
    font-family: var(--ds-font-mono);
    font-size: 0.85em;
  }
  .sky-trigger__arrow {
    color: var(--ds-color-text-subtle);
  }
  .sky-trigger__sub {
    margin: 0;
    font-size: var(--ds-text-sm);
    color: var(--ds-color-text-muted);
  }
  .sky-trigger__tools {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--ds-space-2);
  }
  .sky-trigger__acts {
    display: flex;
    align-items: center;
    gap: var(--ds-space-2);
  }
  .sky-trigger__acts[data-at='head'] {
    display: none;
  }
  .sky-trigger__acts[data-at='foot'] {
    padding-top: var(--ds-space-4);
    border-top: var(--ds-border-width) solid var(--sky-color-divider);
  }
  .sky-trigger__acts[data-at='foot'] > :global(:first-child) {
    flex-grow: 1;
  }
  .sky-trigger__json {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-4);
  }
  .sky-trigger__block {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-2);
    min-width: 0;
  }
  .sky-trigger__label {
    font-family: var(--ds-font-mono);
    font-size: var(--sky-text-label);
    letter-spacing: var(--sky-tracking-label);
    text-transform: uppercase;
    color: var(--ds-color-text-subtle);
  }
  .sky-trigger__block pre {
    margin: 0;
    padding: var(--ds-space-4);
    border-radius: var(--sky-radius-control);
    border: var(--ds-border-width) solid var(--ds-color-border);
    background: var(--ds-color-bg);
    font-family: var(--ds-font-mono);
    font-size: var(--ds-text-xs);
    line-height: var(--ds-line-height-code);
    color: var(--ds-color-text-muted);
    overflow-x: auto;
  }
  .sky-trigger__log {
    display: flex;
    flex-direction: column;
    margin: 0;
    padding: 0;
    list-style: none;
    border-top: var(--ds-border-width) solid var(--sky-color-divider);
  }
  .sky-trigger__fire {
    display: flex;
    align-items: center;
    gap: var(--ds-space-3);
    padding: var(--ds-space-3) 0;
    border-bottom: var(--ds-border-width) solid var(--sky-color-divider);
  }
  .sky-trigger__fire-main {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-0-5);
    flex-grow: 1;
    min-width: 0;
  }
  .sky-trigger__fire-event {
    font-family: var(--ds-font-mono);
    font-size: var(--ds-text-sm);
    overflow-wrap: anywhere;
  }
  .sky-trigger__fire-meta {
    display: flex;
    flex-wrap: wrap;
    gap: var(--ds-space-2-5);
    font-size: var(--ds-text-xs);
    color: var(--ds-color-text-subtle);
  }
  .sky-trigger__fire-link {
    flex-shrink: 0;
    font-size: var(--ds-text-xs);
    color: var(--ds-color-text-muted);
    text-decoration: none;
    white-space: nowrap;
  }
  .sky-trigger__fire-link span {
    font-family: var(--ds-font-mono);
  }
  .sky-trigger__fire-link:hover {
    color: var(--ds-color-fg);
  }
  .sky-trigger__fire-link:focus-visible {
    outline: var(--sky-focus-ring-width) solid var(--sky-color-focus);
    outline-offset: var(--sky-focus-ring-offset);
  }
  @media (pointer: coarse) {
    .sky-trigger__fire-link {
      display: inline-flex;
      align-items: center;
      min-height: var(--sky-size-touch);
    }
  }
  @media (min-width: 48rem) {
    .sky-trigger__head {
      flex-direction: row;
      align-items: flex-start;
      justify-content: space-between;
    }
    .sky-trigger__title {
      font-size: var(--ds-text-2xl);
    }
    /* Board: Readable/JSON, Pause and Delete sit on one row. */
    .sky-trigger__tools {
      flex-wrap: nowrap;
      flex-shrink: 0;
    }
    .sky-trigger__acts[data-at='head'] {
      display: flex;
    }
    .sky-trigger__acts[data-at='foot'] {
      display: none;
    }
  }
</style>
