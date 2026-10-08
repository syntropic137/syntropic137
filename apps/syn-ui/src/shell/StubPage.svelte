<!--
  Placeholder used by the route stubs until each screen is built. Screen
  agents replace their route file and stop importing this.
-->
<script lang="ts">
  import type { Snippet } from 'svelte'

  let {
    title,
    boards,
    loading = false,
    error = undefined,
    facts = [],
    children,
  }: {
    title: string
    /** Canvas boards this screen is built from. */
    boards: string
    loading?: boolean
    error?: unknown
    /** Label/value pairs proving the data path works. */
    facts?: Array<[string, string | number]>
    children?: Snippet
  } = $props()
</script>

<section class="sky-stub" aria-busy={loading}>
  <p class="sky-stub__eyebrow">Skyline · not built yet</p>
  <h1 class="sky-stub__title">{title}</h1>
  <p class="sky-stub__boards">Boards: {boards}</p>
  {#if error}
    <p class="sky-stub__error" role="alert">{error instanceof Error ? error.message : String(error)}</p>
  {:else if loading && facts.length === 0}
    <p class="sky-stub__muted">Loading…</p>
  {/if}
  {#if facts.length > 0}
    <dl class="sky-stub__facts">
      {#each facts as [label, value] (label)}
        <div><dt>{label}</dt><dd>{value}</dd></div>
      {/each}
    </dl>
  {/if}
  {@render children?.()}
</section>

<style>
  .sky-stub {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-3);
    padding: var(--ds-space-5);
    border-radius: var(--sky-radius-2xl);
    border: var(--ds-border-width) solid var(--ds-color-border);
    background: radial-gradient(70% 70% at 100% 0%, var(--sky-color-hero-glow), transparent 70%), var(--ds-color-surface);
    box-shadow: var(--sky-shadow-raised-strong);
  }
  .sky-stub__eyebrow,
  .sky-stub__facts dt {
    margin: 0;
    font-family: var(--ds-font-mono);
    font-size: var(--sky-text-label);
    letter-spacing: var(--sky-tracking-label);
    text-transform: uppercase;
    color: var(--ds-color-text-subtle);
  }
  .sky-stub__title {
    margin: 0;
    font-size: var(--sky-text-page);
    line-height: var(--ds-line-height-tight);
    font-weight: var(--ds-font-weight-semibold);
    letter-spacing: var(--sky-tracking-display);
  }
  .sky-stub__boards,
  .sky-stub__muted {
    margin: 0;
    color: var(--ds-color-text-muted);
  }
  .sky-stub__error {
    margin: 0;
    color: var(--ds-color-danger);
  }
  .sky-stub__facts {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: var(--ds-space-4);
    margin: var(--ds-space-2) 0 0;
  }
  .sky-stub__facts dd {
    margin: var(--ds-space-1) 0 0;
    font-size: var(--sky-text-figure);
    font-weight: var(--ds-font-weight-semibold);
    letter-spacing: -0.03em;
    font-variant-numeric: tabular-nums;
    overflow-wrap: anywhere;
  }
  @media (min-width: 48rem) {
    .sky-stub {
      padding: var(--ds-space-8) var(--ds-space-9);
    }
    .sky-stub__facts {
      grid-template-columns: repeat(auto-fit, minmax(10rem, 1fr));
    }
  }
</style>
