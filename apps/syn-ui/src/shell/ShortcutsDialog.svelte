<!--
  The `?` overlay: every binding in skyline-core's KEYMAP, the same list
  the keyboard handler reads, so the two cannot drift. Lazy chunk.
-->
<script lang="ts">
  import { KEYMAP, keymapGroups, sequenceLabel } from '@syn137/skyline-core/state'
  import { Dialog } from '@syn137/skyline-svelte-v5'
  import { Keycaps } from '@syn137/skyline-svelte-v5/patterns'
  import { tokenCaps } from './keycaps'
  import { DOCS_URL, FEATURE_REQUESTS_URL, ISSUES_URL } from '../lib/links'
  import { feedbackUi } from './feedback.svelte'
  import { APPLE, overlays } from './overlays.svelte'

  // Bindings for a feature that is off (feedback outside a dev machine) are not listed.
  const groups = $derived(keymapGroups(KEYMAP, feedbackUi.enabled ? ['feedback'] : []))
</script>

<Dialog bind:open={overlays.shortcuts} title="Keyboard shortcuts" size="md">
  <div class="sky-keys">
    {#each groups as g (g.group)}
      <section class="sky-keys__group" aria-label={g.group}>
        <h3 class="sky-keys__heading">{g.group}</h3>
        <dl class="sky-keys__list">
          {#each g.bindings as b (b.id)}
            <div class="sky-keys__row" data-binding={b.id}>
              <dt class="sky-keys__label">{b.label}</dt>
              <dd class="sky-keys__keys">
                {#each b.keys as seq, i (i)}
                  {#if i > 0}<span class="sky-keys__or">or</span>{/if}
                  {#each seq as token, j (j)}<Keycaps keys={tokenCaps(token, APPLE)} label={sequenceLabel([token], APPLE)} />{/each}
                {/each}
              </dd>
            </div>
          {/each}
        </dl>
      </section>
    {/each}
  </div>
  {#snippet footer()}
    <nav class="sky-keys__links" aria-label="Help">
      <a href={DOCS_URL} target="_blank" rel="noopener">Documentation</a>
      <a href={FEATURE_REQUESTS_URL} target="_blank" rel="noopener">Request a feature</a>
      <a href={ISSUES_URL} target="_blank" rel="noopener">Report an issue</a>
    </nav>
  {/snippet}
</Dialog>

<style>
  .sky-keys {
    display: grid;
    gap: var(--ds-space-5);
  }
  .sky-keys__group {
    display: grid;
    gap: var(--ds-space-2);
  }
  .sky-keys__heading {
    margin: 0;
    font-family: var(--ds-font-mono);
    font-size: var(--sky-text-label);
    font-weight: var(--ds-font-weight-medium);
    letter-spacing: var(--sky-tracking-label);
    text-transform: uppercase;
    color: var(--ds-color-text-subtle);
  }
  .sky-keys__list {
    display: grid;
    gap: var(--ds-space-1);
    margin: 0;
  }
  .sky-keys__row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--ds-space-3);
    min-height: var(--sky-size-control-sm);
  }
  .sky-keys__label {
    font-size: var(--ds-text-sm);
    color: var(--ds-color-fg);
  }
  .sky-keys__keys {
    display: flex;
    flex-wrap: wrap;
    justify-content: flex-end;
    align-items: center;
    gap: var(--ds-space-1);
    margin: 0;
  }
  .sky-keys__or {
    font-size: var(--sky-text-label);
    color: var(--ds-color-text-subtle);
  }
  .sky-keys__links {
    display: flex;
    flex-wrap: wrap;
    gap: var(--ds-space-2) var(--ds-space-4);
    font-size: var(--ds-text-sm);
  }
  .sky-keys__links a {
    color: var(--ds-color-text-muted);
  }
  .sky-keys__links a:hover {
    color: var(--ds-color-fg);
  }
  .sky-keys__links a:focus-visible {
    outline: var(--sky-focus-ring-width) solid var(--sky-color-focus);
    outline-offset: var(--sky-focus-ring-offset);
  }
  @media (pointer: coarse) {
    .sky-keys__links a {
      display: inline-flex;
      align-items: center;
      min-height: var(--sky-size-touch);
    }
  }
</style>
