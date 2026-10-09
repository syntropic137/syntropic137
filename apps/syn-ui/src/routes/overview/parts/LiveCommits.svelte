<!-- Live commits: git events from the activity stream, newest first. -->
<script lang="ts">
  import GitCommit from '@lucide/svelte/icons/git-commit-horizontal'
  import { formatRelativeTime } from '@syn137/skyline-core/format'
  import type { LiveState } from '@syn137/skyline-core/patterns'
  import type { LiveCommit } from '@syn137/skyline-core/screens/overview'

  let { commits, state, loading = false }: { commits: LiveCommit[]; state: LiveState; loading?: boolean } = $props()

  const idle = $derived(
    loading
      ? 'Loading recent commits.'
      : state === 'fixtures'
      ? 'Fixtures mode, no live stream.'
      : state === 'live'
        ? 'Listening. No git events yet, push to a connected repo and it shows here.'
        : 'Connecting to the activity stream.',
  )
</script>

<section class="sky-ov-commits" aria-labelledby="sky-ov-commits-title" aria-live="polite" data-empty={commits.length === 0 || undefined}>
  <div class="sky-ov-commits__head">
    <GitCommit size={16} aria-hidden="true" />
    <h3 id="sky-ov-commits-title">Live commits</h3>
    {#if commits.length === 0}<span>{idle}</span>{/if}
  </div>
  {#if commits.length}
    <ul>
      {#each commits as c (c.id)}
        <li>
          {#if c.url}
            <a class="sky-ov-mono" data-tone="fg" href={c.url} target="_blank" rel="noreferrer">{c.hash}</a>
          {:else}
            <span class="sky-ov-mono" data-tone="fg">{c.hash}</span>
          {/if}
          <span class="sky-ov-commits__msg">{c.message}</span>
          <span class="sky-ov-mono">{[c.repo, c.branch].filter(Boolean).join(' · ')}</span>
          <span class="sky-ov-mono">{formatRelativeTime(c.at)}</span>
        </li>
      {/each}
    </ul>
  {/if}
</section>

<style>
  .sky-ov-commits {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-2-5);
    margin-top: var(--ds-space-1-5);
    padding: var(--ds-space-3-5) var(--ds-space-4);
    border-radius: var(--sky-radius-row);
    border: var(--ds-border-width) dashed var(--sky-color-border-strong);
    font-size: var(--ds-text-sm);
    color: var(--ds-color-text-muted);
  }
  .sky-ov-commits__head {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--ds-space-3);
  }
  .sky-ov-commits h3 {
    margin: 0;
    font-size: inherit;
    font-weight: var(--ds-font-weight-semibold);
    color: var(--ds-color-fg);
  }
  ul {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-2);
    margin: 0;
    padding: 0;
    list-style: none;
  }
  li {
    display: flex;
    flex-wrap: wrap;
    align-items: baseline;
    gap: var(--ds-space-1) var(--ds-space-3);
  }
  a {
    text-decoration: none;
  }
  a:focus-visible {
    outline: var(--sky-focus-ring-width) solid var(--sky-color-focus);
    outline-offset: var(--sky-focus-ring-offset);
  }
  .sky-ov-commits__msg {
    flex: 1 1 12rem;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    color: var(--ds-color-fg);
  }
</style>
