<!--
  Repos. No board yet (spec phase 4: card list, status badge), built in the
  Triggers/Artifact language. Registered repos merged with what the GitHub
  App reaches: owning system, App attachment and privacy. Read-only; repos
  are registered from the CLI.
-->
<script lang="ts">
  import { listRepos, listSystems, lookUpAppAccess } from '@syn137/syn-ui-data'
  import type { AppAccess, SystemSummary } from '@syn137/syn-ui-data'
  import { Button, Callout, EmptyState, Input, Skeleton } from '@syn137/skyline-svelte-v5'
  import { ObjectIcon } from '@syn137/skyline-svelte-v5/patterns'
  import { formatDate } from '@syn137/skyline-core/format'
  import { groupReposByOwner, repoCounts, repoRows, type RepoRow } from '@syn137/skyline-core/screens/repos'
  import { resource } from '../../lib/load.svelte'
  import type { PageProps } from '../../lib/routes'

  let { params: _params }: PageProps = $props()

  const data = resource(async (signal) => {
    const [repos, systems, access] = await Promise.all([
      listRepos(signal),
      // Names only: rows are still worth showing without them.
      listSystems(signal).catch((): SystemSummary[] => []),
      lookUpAppAccess(signal).catch((): AppAccess => ({ repos: [], complete: false })),
    ])
    return { rows: repoRows(repos, systems, access), complete: access.complete }
  })

  let search = $state('')
  const rows = $derived(data.data?.rows ?? [])
  const shown = $derived(search.trim() ? rows.filter((r) => `${r.fullName} ${r.system ?? ''}`.toLowerCase().includes(search.trim().toLowerCase())) : rows)
  const groups = $derived(groupReposByOwner(shown))
  const counts = $derived(repoCounts(rows))
  const errorText = $derived(data.error instanceof Error ? data.error.message : 'The server did not answer.')

  const attachLabel: Record<RepoRow['attachment'], string> = { attached: 'App attached', 'not-attached': 'Not attached', unknown: 'Attachment unknown' }
</script>

<div class="sky-repos">
  <section class="sky-repos__head" aria-labelledby="sky-repos-title">
    <div class="sky-repos__id">
      <span class="sky-repos__icon"><ObjectIcon kind="workflow" size={84} /></span>
      <div>
        <h1 id="sky-repos-title" class="sky-repos__title">Repos</h1>
        <p class="sky-repos__lead">
          Repositories registered with the platform or reachable by the GitHub App.
          {#if data.data && rows.length}<span class="sky-repos__count">{counts.total} connected, {counts.attached} with the App.</span>{/if}
        </p>
      </div>
    </div>
    {#if rows.length > 4}
      <div class="sky-repos__search"><Input type="search" aria-label="Search repos" placeholder="Repo or system" bind:value={search} /></div>
    {/if}
  </section>

  {#if data.error && !data.data}
    <Callout tone="danger" title="Couldn't load repositories." role="alert">
      {errorText}
      {#snippet action()}<Button size="sm" onclick={() => data.refresh()}>Retry</Button>{/snippet}
    </Callout>
  {:else if !data.data}
    <div class="sky-repos__list" aria-busy="true"><Skeleton lines={6} label="Loading repos" /></div>
  {:else if rows.length === 0}
    <EmptyState title="No repositories attached" description="Register one with syn repo register --url owner/repo, then install the GitHub App on it so workflows can act on it." />
  {:else}
    {#if !data.data.complete}
      <Callout tone="warning" title="GitHub didn't answer for every installation.">Some repos show attachment as unknown; they may still be reachable.</Callout>
    {/if}
    {#if shown.length === 0}
      <EmptyState title="No repos match" description="Try another name or system.">
        {#snippet action()}<Button size="sm" onclick={() => (search = '')}>Clear search</Button>{/snippet}
      </EmptyState>
    {/if}
    {#each groups as g (g.owner)}
      <section class="sky-repos__list" aria-label={g.owner}>
        <div class="sky-repos__owner">
          <span>{g.owner}</span>
          <span class="sky-repos__n">{g.repos.length} {g.repos.length === 1 ? 'repo' : 'repos'}</span>
        </div>
        <ul class="sky-repos__rows">
          {#each g.repos as r (r.key)}
            <li class="sky-repos__row">
              <span class="sky-repos__glyph" aria-hidden="true">
                <svg width="15" height="15" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M4.5 2.75h8v10.5h-8a1.5 1.5 0 0 1-1.5-1.5v-7.5a1.5 1.5 0 0 1 1.5-1.5zM3 11.75a1.5 1.5 0 0 1 1.5-1.5h8"></path></svg>
              </span>
              <span class="sky-repos__main">
                <span class="sky-repos__name">
                  <span>{r.name}</span>
                  {#if r.privacy === 'private'}
                    <span class="sky-repos__pill" title="Private repository">Private</span>
                  {:else if r.privacy === 'unknown'}
                    <span class="sky-repos__pill" title="Privacy not visible: the GitHub App cannot reach this repo, and registration does not record it">Privacy unknown</span>
                  {/if}
                </span>
                <span class="sky-repos__meta">
                  {#if r.registered}
                    <span>{r.system ? `System ${r.system}` : 'No system'}</span>
                  {:else}
                    <span title="Reachable by the GitHub App; not registered with syn repo register">Not registered</span>
                  {/if}
                  {#if r.defaultBranch}<span class="sky-repos__mono">{r.defaultBranch}</span>{/if}
                  {#if r.createdAt}<span>added {formatDate(r.createdAt)}</span>{/if}
                </span>
              </span>
              <span class="sky-repos__attach" data-state={r.attachment}>
                <span class="sky-repos__dot" aria-hidden="true"></span>{attachLabel[r.attachment]}
              </span>
            </li>
          {/each}
        </ul>
      </section>
    {/each}
  {/if}
</div>

<style>
  .sky-repos {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-5);
    min-width: 0;
  }
  .sky-repos__head {
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
  .sky-repos__id {
    display: flex;
    align-items: center;
    gap: var(--ds-space-4);
  }
  .sky-repos__icon {
    flex-shrink: 0;
    width: 3rem;
  }
  .sky-repos__icon :global(svg) {
    width: 100%;
    height: auto;
  }
  .sky-repos__title {
    margin: 0;
    font-size: var(--sky-text-page);
    line-height: var(--ds-line-height-tight);
    font-weight: var(--ds-font-weight-semibold);
    letter-spacing: var(--sky-tracking-display);
  }
  .sky-repos__lead {
    margin: var(--ds-space-1-5) 0 0;
    font-size: var(--ds-text-sm);
    color: var(--ds-color-text-muted);
  }
  .sky-repos__count {
    color: var(--ds-color-text-subtle);
  }
  .sky-repos__list {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-1);
    padding: var(--ds-space-3);
    border-radius: var(--sky-radius-card-lg);
    border: var(--ds-border-width) solid var(--ds-color-border);
    background: var(--ds-color-surface);
    box-shadow: var(--sky-shadow-raised);
  }
  .sky-repos__owner {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: var(--ds-space-3);
    padding: var(--ds-space-2) var(--ds-space-2) var(--ds-space-1);
    font-family: var(--ds-font-mono);
    font-size: var(--ds-text-xs);
    color: var(--ds-color-text-muted);
  }
  .sky-repos__n {
    color: var(--ds-color-text-subtle);
  }
  .sky-repos__rows {
    display: flex;
    flex-direction: column;
    margin: 0;
    padding: 0;
    list-style: none;
  }
  .sky-repos__row {
    display: grid;
    grid-template-columns: auto minmax(0, 1fr);
    align-items: center;
    gap: var(--ds-space-2) var(--ds-space-3);
    padding: var(--ds-space-3) var(--ds-space-2);
    border-top: var(--ds-border-width) solid var(--sky-color-divider);
  }
  .sky-repos__glyph {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 2rem;
    height: 2rem;
    border-radius: var(--sky-radius-control);
    background: var(--ds-color-surface-raised);
    color: var(--ds-color-text-muted);
  }
  .sky-repos__main {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-0-5);
    min-width: 0;
  }
  .sky-repos__name {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--ds-space-2);
    font-weight: var(--ds-font-weight-semibold);
    overflow-wrap: anywhere;
  }
  .sky-repos__pill {
    padding: 0 var(--ds-space-2);
    border-radius: var(--ds-radius-full);
    border: var(--ds-border-width) solid var(--sky-color-border-strong);
    font-size: var(--ds-text-xs);
    font-weight: var(--ds-font-weight-regular);
    color: var(--ds-color-text-muted);
  }
  .sky-repos__meta {
    display: flex;
    flex-wrap: wrap;
    gap: var(--ds-space-2-5);
    font-size: var(--ds-text-xs);
    color: var(--ds-color-text-subtle);
  }
  .sky-repos__mono {
    font-family: var(--ds-font-mono);
  }
  .sky-repos__attach {
    grid-column: 2;
    justify-self: start;
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
    white-space: nowrap;
  }
  .sky-repos__attach[data-state='attached'] {
    background: var(--sky-color-accent-soft);
    color: var(--sky-color-accent-soft-fg);
  }
  .sky-repos__attach[data-state='unknown'] {
    background: var(--sky-color-warning-soft);
    color: var(--sky-color-warning-soft-fg);
  }
  .sky-repos__dot {
    width: 6px;
    height: 6px;
    border-radius: var(--ds-radius-full);
    background: currentColor;
  }
  @media (min-width: 48rem) {
    .sky-repos__head {
      flex-direction: row;
      align-items: center;
      justify-content: space-between;
      gap: var(--ds-space-8);
      padding: var(--ds-space-8) var(--ds-space-9);
    }
    .sky-repos__id {
      gap: var(--ds-space-6);
    }
    .sky-repos__icon {
      width: 5.25rem;
    }
    .sky-repos__search {
      flex: 0 1 22rem;
    }
    .sky-repos__row {
      grid-template-columns: auto minmax(0, 1fr) auto;
    }
    .sky-repos__attach {
      grid-column: 3;
    }
  }
</style>
