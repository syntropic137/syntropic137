<!--
  The running build (owner, Oct 8 2026: "I don't see the version anywhere").
  `mark`: a small mono version under the wordmark; hover or focus shows the
  full build, click copies it. `block`: the same rows inline, for the phone
  More sheet and the `?` overlay footer. A bundle from another release than
  the API's (a rollout in flight, a stale tab) shows a quiet warning.
-->
<script lang="ts">
  import { writeClipboard } from '@syn137/skyline-svelte-v5'
  import { useBuild } from './build.svelte'

  let { variant = 'mark' }: { variant?: 'mark' | 'block' } = $props()

  const build = useBuild()
  const view = $derived(build.view)
  let copied = $state(false)
  let dismissed = $state(false)
  const uid = $props.id()
  const tipId = `${uid}-build`

  async function copy() {
    try {
      await writeClipboard(view.text)
    } catch {
      return // Clipboard refused: the rows stay on screen to read.
    }
    copied = true
    setTimeout(() => (copied = false), 1500)
  }
</script>

{#if variant === 'mark'}
  {#if view.label}
    <!-- A CSS tooltip, not the Tooltip component: the mark is in every first load, and the component's layer code would cost ~6 KB gzip. -->
    <div class="sky-build-mark-wrap" data-dismissed={dismissed || undefined}>
      <button
        type="button"
        class="sky-build-mark"
        data-testid="build-version"
        data-state={view.mismatch ? 'mismatch' : undefined}
        aria-describedby={tipId}
        aria-label={`Version ${view.label}${view.mismatch ? ', UI from another release' : ''}. Copy build details`}
        onclick={copy}
        onblur={() => (dismissed = false)}
        onpointerenter={() => (dismissed = false)}
        onkeydown={(e) => {
          if (e.key === 'Escape') dismissed = true
        }}
      >{view.label}</button>
      <div class="sky-build-tip" role="tooltip" id={tipId}>
        <dl class="sky-build-tip__rows">
          {#each view.details as d (d.term)}<div><dt>{d.term}</dt><dd>{d.value}</dd></div>{/each}
        </dl>
        <span class="sky-build-tip__hint">{copied ? 'Copied' : 'Click to copy'}{view.mismatch ? ' · UI and API releases differ: reload' : ''}</span>
      </div>
    </div>
  {/if}
{:else}
  <div class="sky-build-block" data-testid="build-block" data-state={view.mismatch ? 'mismatch' : undefined}>
    <dl class="sky-build-block__rows">
      {#each view.details as d (d.term)}<div><dt>{d.term}</dt><dd>{d.value}</dd></div>{/each}
    </dl>
    {#if view.mismatch}<p class="sky-build-block__warn">This tab loaded another UI release than the API runs. Reload to match.</p>{/if}
    <button type="button" class="sky-build-block__copy" onclick={copy}>{copied ? 'Copied' : 'Copy build'}</button>
  </div>
{/if}

<style>
  .sky-build-mark {
    padding: 0 var(--ds-space-1);
    border: 0;
    border-radius: var(--ds-radius-xs);
    background: none;
    font-family: var(--ds-font-mono);
    font-size: var(--sky-text-label);
    line-height: var(--ds-line-height-snug);
    color: var(--sky-color-text-faint);
    white-space: nowrap;
    cursor: pointer;
  }
  .sky-build-mark:hover,
  .sky-build-mark:focus-visible {
    color: var(--ds-color-text-subtle);
  }
  .sky-build-mark[data-state='mismatch'] {
    text-decoration: underline dotted;
    text-underline-offset: 0.2em;
  }
  .sky-build-block__warn {
    color: var(--sky-color-warning-soft-fg);
  }
  .sky-build-mark:focus-visible,
  .sky-build-block__copy:focus-visible {
    outline: var(--sky-focus-ring-width) solid var(--sky-color-focus);
    outline-offset: var(--sky-focus-ring-offset);
  }
  .sky-build-mark-wrap {
    position: relative;
    display: inline-flex;
  }
  .sky-build-tip {
    position: absolute;
    top: calc(100% + var(--ds-space-1-5));
    left: 0;
    z-index: var(--sky-z-overlay);
    display: none;
    width: max-content;
    max-width: 18rem;
    padding: var(--ds-space-2) var(--ds-space-2-5);
    border-radius: var(--ds-radius-md);
    border: var(--ds-border-width) solid var(--sky-color-border-strong);
    background: var(--ds-color-surface-raised);
    box-shadow: var(--sky-shadow-overlay);
  }
  .sky-build-mark-wrap:hover .sky-build-tip,
  .sky-build-mark-wrap:has(.sky-build-mark:focus-visible) .sky-build-tip {
    display: block;
  }
  .sky-build-mark-wrap[data-dismissed] .sky-build-tip {
    display: none;
  }
  .sky-build-tip__rows,
  .sky-build-block__rows {
    display: grid;
    grid-template-columns: auto 1fr;
    gap: var(--ds-space-0-5) var(--ds-space-3);
    margin: 0;
    font-family: var(--ds-font-mono);
    font-size: var(--sky-text-label);
  }
  .sky-build-tip__rows div,
  .sky-build-block__rows div {
    display: contents;
  }
  .sky-build-tip__rows dt,
  .sky-build-block__rows dt {
    color: var(--ds-color-text-subtle);
  }
  .sky-build-tip__rows dd,
  .sky-build-block__rows dd {
    margin: 0;
    color: var(--ds-color-fg);
  }
  .sky-build-tip__hint {
    display: block;
    margin-top: var(--ds-space-1-5);
    font-size: var(--sky-text-label);
    color: var(--ds-color-text-muted);
  }
  .sky-build-block {
    display: grid;
    gap: var(--ds-space-2);
  }
  .sky-build-block__warn {
    margin: 0;
    font-size: var(--sky-text-label);
  }
  .sky-build-block__copy {
    justify-self: start;
    padding: 0;
    border: 0;
    background: none;
    font: inherit;
    font-size: var(--sky-text-label);
    color: var(--ds-color-text-muted);
    text-decoration: underline;
    cursor: pointer;
  }
  .sky-build-block__copy:hover {
    color: var(--ds-color-fg);
  }
  @media (pointer: coarse) {
    .sky-build-mark,
    .sky-build-block__copy {
      min-height: var(--sky-size-touch);
    }
  }
</style>
