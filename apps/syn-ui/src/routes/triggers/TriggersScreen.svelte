<!--
  Triggers (board Triggers, PhoneTriggers): header panel with search and a
  status filter, rules grouped by repo with an active/paused Switch, and the
  selected rule as a Rule Sentence. From 64rem the rule sits in a column
  beside the list; on a phone it opens in place under its row.
-->
<script lang="ts">
  import { listTriggers, updateTrigger } from '@syn137/syn-ui-data'
  import type { TriggerSummary } from '@syn137/syn-ui-data'
  import { Button, Callout, EmptyState, Input, Skeleton, Switch, ToggleGroup } from '@syn137/skyline-svelte-v5'
  import { ObjectIcon } from '@syn137/skyline-svelte-v5/patterns'
  import { filterTriggers, groupTriggersByRepo, triggerSummary, triggerTitle } from '@syn137/skyline-core/screens/triggers'
  import { onMount } from 'svelte'
  import { isRunEvent } from '@syn137/syn-ui-data/live'
  import { resource } from '../../lib/load.svelte'
  import { setPage } from '../../lib/page.svelte'
  import { href, router } from '../../lib/router'
  import TriggerPanel from './TriggerPanel.svelte'

  let { selectedId }: { selectedId: string | null } = $props()

  const list = resource((signal) => listTriggers({}, signal), { live: isRunEvent })

  let wide = $state(false)
  onMount(() => {
    const mq = matchMedia('(min-width: 64rem)')
    const sync = () => (wide = mq.matches)
    sync()
    mq.addEventListener('change', sync)
    return () => mq.removeEventListener('change', sync)
  })

  const status = $derived(router.query.get('status') ?? 'all')
  let search = $state(router.query.get('q') ?? '')
  const all = $derived(list.data?.triggers ?? [])
  const shown = $derived(filterTriggers(all, { q: search, status }))
  const groups = $derived(groupTriggersByRepo(shown))
  const counts = $derived({ active: all.filter((t) => t.status === 'active').length, paused: all.filter((t) => t.status === 'paused').length })

  // Wide screens always show a rule: the chosen one, or the first in the list.
  const openId = $derived(selectedId ?? (wide ? (shown[0]?.trigger_id ?? null) : null))
  const selectedMissing = $derived(Boolean(selectedId && list.data && !all.some((t) => t.trigger_id === selectedId)))

  $effect(() => {
    if (!selectedId) setPage({ title: 'Triggers', crumbs: [{ label: 'Triggers' }] })
  })

  const pending = $state<Record<string, boolean>>({})
  let switchError = $state<string | null>(null)
  async function setActive(t: TriggerSummary, on: boolean) {
    pending[t.trigger_id] = true
    switchError = null
    try {
      await updateTrigger(t.trigger_id, on ? 'resume' : 'pause')
    } catch (e) {
      switchError = `${triggerTitle(t)}: ${e instanceof Error ? e.message : 'the server refused the change.'}`
    } finally {
      pending[t.trigger_id] = false
      list.refresh()
    }
  }

  const rowHref = (id: string) => (!wide && id === selectedId ? href('/triggers') : href(`/triggers/${encodeURIComponent(id)}`))
  const errorText = $derived(list.error instanceof Error ? list.error.message : 'The server did not answer.')
</script>

<div class="sky-triggers">
  <section class="sky-triggers__head" aria-labelledby="sky-triggers-title">
    <div class="sky-triggers__id">
      <span class="sky-triggers__icon"><ObjectIcon kind="trigger" size={84} /></span>
      <div>
        <h1 id="sky-triggers-title" class="sky-triggers__title">Triggers</h1>
        <p class="sky-triggers__lead">GitHub events that start a workflow on their own. {list.data ? triggerSummary(all) : ''}</p>
      </div>
    </div>
    <div class="sky-triggers__filters">
      <Input type="search" aria-label="Search triggers" placeholder="Event, repo or workflow" bind:value={search} />
      <ToggleGroup
        type="single"
        variant="chips"
        aria-label="Status"
        value={[status]}
        onValueChange={(v) => router.setQuery({ status: v[0] && v[0] !== 'all' ? v[0] : null })}
        items={[
          { value: 'all', label: 'All' },
          { value: 'active', label: 'Active', count: counts.active },
          { value: 'paused', label: 'Paused', count: counts.paused },
        ]}
      />
    </div>
  </section>

  {#if list.error && !list.data}
    <Callout tone="danger" title="Couldn't load triggers." role="alert">
      {errorText}
      {#snippet action()}<Button size="sm" onclick={() => list.refresh()}>Retry</Button>{/snippet}
    </Callout>
  {:else if !list.data}
    <div class="sky-triggers__body" aria-busy="true">
      <div class="sky-triggers__list"><Skeleton lines={7} label="Loading triggers" /></div>
      {#if wide}<div class="sky-triggers__detail"><Skeleton lines={6} /></div>{/if}
    </div>
  {:else if all.length === 0}
    <EmptyState title="No triggers yet" description="Create one from the CLI: syn triggers create --event check_run.completed --repo owner/repo --workflow <id>. Rules then fire on their own." />
  {:else}
    {#if switchError}<Callout tone="danger" title="That didn't work." role="alert">{switchError}</Callout>{/if}
    {#if selectedMissing}
      <Callout tone="warning" title="That trigger is gone.">No trigger has the ID {selectedId}. It may have been deleted.</Callout>
    {/if}
    <div class="sky-triggers__body">
      <section class="sky-triggers__list" aria-label="Trigger rules">
        {#if shown.length === 0}
          <EmptyState bare level={3} title="No rules match" description="Clear the search or pick another status.">
            {#snippet action()}<Button size="sm" onclick={() => { search = ''; router.setQuery({ status: null }) }}>Clear filters</Button>{/snippet}
          </EmptyState>
        {/if}
        {#each groups as g (g.repo)}
          <div class="sky-triggers__group">
            <div class="sky-triggers__repo">
              <span>{g.repo}</span>
              <span class="sky-triggers__n">{g.rules.length} {g.rules.length === 1 ? 'rule' : 'rules'}</span>
            </div>
            <ul class="sky-triggers__rules">
              {#each g.rules as t (t.trigger_id)}
                <li>
                  <div class="sky-triggers__row" data-open={openId === t.trigger_id ? true : undefined}>
                    <span class="sky-triggers__bolt" aria-hidden="true">
                      <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"><path d="M9 1.75L3.5 9h4l-1 5.25L12.5 7h-4z"></path></svg>
                    </span>
                    <a class="sky-triggers__link" href={rowHref(t.trigger_id)} aria-current={openId === t.trigger_id ? 'true' : undefined} aria-expanded={wide ? undefined : openId === t.trigger_id}>
                      <span class="sky-triggers__event">{t.event}</span>
                      <span class="sky-triggers__sub">runs {t.workflow_name ?? t.workflow_id} · fired {t.fire_count}×</span>
                    </a>
                    <Switch
                      checked={t.status === 'active'}
                      disabled={pending[t.trigger_id] || t.status === 'deleted'}
                      aria-label={`${t.event} on ${g.repo} is ${t.status === 'active' ? 'active' : 'paused'}`}
                      onCheckedChange={(on) => setActive(t, on)}
                    />
                  </div>
                  {#if !wide && openId === t.trigger_id}
                    <div class="sky-triggers__inplace">
                      <TriggerPanel triggerId={t.trigger_id} setCrumbs onchanged={() => list.refresh()} />
                    </div>
                  {/if}
                </li>
              {/each}
            </ul>
          </div>
        {/each}
      </section>

      {#if wide && openId}
        <div class="sky-triggers__detail">
          {#key openId}
            <TriggerPanel triggerId={openId} setCrumbs={Boolean(selectedId)} onchanged={() => list.refresh()} />
          {/key}
        </div>
      {/if}
    </div>
  {/if}
</div>

<style>
  .sky-triggers {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-5);
    min-width: 0;
  }
  .sky-triggers__head {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-5);
    padding: var(--ds-space-5);
    border-radius: var(--sky-radius-2xl);
    border: var(--ds-border-width) solid var(--ds-color-border);
    background:
      radial-gradient(50% 130% at 100% 0%, var(--sky-color-hero-glow), transparent 70%),
      var(--ds-color-surface);
    box-shadow: var(--sky-shadow-raised);
  }
  .sky-triggers__id {
    display: flex;
    align-items: center;
    gap: var(--ds-space-4);
  }
  .sky-triggers__icon {
    flex-shrink: 0;
    width: 3rem;
  }
  .sky-triggers__icon :global(svg) {
    width: 100%;
    height: auto;
  }
  .sky-triggers__title {
    margin: 0;
    font-size: var(--sky-text-page);
    line-height: var(--ds-line-height-tight);
    font-weight: var(--ds-font-weight-semibold);
    letter-spacing: var(--sky-tracking-display);
  }
  .sky-triggers__lead {
    margin: var(--ds-space-1-5) 0 0;
    font-size: var(--ds-text-sm);
    color: var(--ds-color-text-muted);
  }
  .sky-triggers__filters {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-3);
    min-width: 0;
  }
  .sky-triggers__body {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-5);
    min-width: 0;
  }
  .sky-triggers__list,
  .sky-triggers__detail {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-4);
    min-width: 0;
    padding: var(--ds-space-3);
    border-radius: var(--sky-radius-card-lg);
    border: var(--ds-border-width) solid var(--ds-color-border);
    background: var(--ds-color-surface);
    box-shadow: var(--sky-shadow-raised);
  }
  .sky-triggers__detail {
    padding: var(--ds-space-6);
  }
  .sky-triggers__group {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-1);
  }
  .sky-triggers__repo {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: var(--ds-space-3);
    padding: var(--ds-space-2) var(--ds-space-2) var(--ds-space-1);
    font-family: var(--ds-font-mono);
    font-size: var(--ds-text-xs);
    color: var(--ds-color-text-muted);
    overflow-wrap: anywhere;
  }
  .sky-triggers__n {
    flex-shrink: 0;
    color: var(--ds-color-text-subtle);
  }
  .sky-triggers__rules {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-0-5);
    margin: 0;
    padding: 0;
    list-style: none;
  }
  .sky-triggers__row {
    display: flex;
    align-items: center;
    gap: var(--ds-space-3);
    padding: var(--ds-space-2) var(--ds-space-2);
    border-radius: var(--sky-radius-row);
  }
  .sky-triggers__row:hover {
    background: var(--ds-color-surface-raised);
  }
  .sky-triggers__row[data-open] {
    background: var(--ds-color-overlay);
    box-shadow: var(--sky-shadow-raised);
  }
  .sky-triggers__bolt {
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
    width: 2rem;
    height: 2rem;
    border-radius: var(--sky-radius-control);
    background: var(--sky-color-accent-soft);
    color: var(--sky-color-accent-soft-fg);
  }
  .sky-triggers__link {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-0-5);
    flex-grow: 1;
    min-width: 0;
    border-radius: var(--ds-radius-md);
    color: var(--ds-color-fg);
    text-decoration: none;
  }
  .sky-triggers__link:focus-visible {
    outline: var(--sky-focus-ring-width) solid var(--sky-color-focus);
    outline-offset: var(--sky-focus-ring-offset);
  }
  .sky-triggers__event {
    font-family: var(--ds-font-mono);
    font-size: var(--ds-text-sm);
    font-weight: var(--ds-font-weight-medium);
    overflow-wrap: anywhere;
  }
  .sky-triggers__sub {
    font-size: var(--ds-text-xs);
    color: var(--ds-color-text-subtle);
  }
  .sky-triggers__inplace {
    margin: var(--ds-space-2) 0 var(--ds-space-3);
    padding: var(--ds-space-4);
    border-radius: var(--sky-radius-row);
    border: var(--ds-border-width) solid var(--ds-color-border);
    background: var(--ds-color-bg);
  }
  @media (pointer: coarse) {
    .sky-triggers__link {
      min-height: var(--sky-size-touch);
      justify-content: center;
    }
  }
  @media (min-width: 48rem) {
    .sky-triggers__head {
      flex-direction: row;
      align-items: center;
      justify-content: space-between;
      gap: var(--ds-space-8);
      padding: var(--ds-space-8) var(--ds-space-9);
    }
    .sky-triggers__id {
      gap: var(--ds-space-6);
    }
    .sky-triggers__icon {
      width: 5.25rem;
    }
    .sky-triggers__filters {
      flex: 0 1 26rem;
    }
  }
  @media (min-width: 64rem) {
    .sky-triggers__body {
      display: grid;
      grid-template-columns: minmax(20rem, 26rem) minmax(0, 1fr);
      align-items: start;
      gap: var(--ds-space-8);
    }
    .sky-triggers__detail {
      position: sticky;
      top: var(--ds-space-4);
      padding: var(--ds-space-8);
    }
  }
</style>
