<!--
  Harness Chip (Landing hero and pillar 02; the app's Execution, Workflow
  and Session pages later): which harness runs a phase, as a small pill with
  a dot in the harness colour (--sky-harness-*, the dot takes the gradient).
-->
<script lang="ts">
  import { harnessLook } from '@syn137/skyline-core/patterns'
  import type { HarnessChipProps } from './types'

  let { provider, label, ...rest }: HarnessChipProps = $props()

  const look = $derived(harnessLook(provider))
  const text = $derived(label ?? provider)
</script>

<span {...rest} class="sky-harness-chip" data-provider={look.provider} title={rest.title ?? look.name}>
  <span class="sky-harness-chip__dot" aria-hidden="true" style:background={`var(${look.gradient})`}></span>{text}
</span>

<style>
  .sky-harness-chip {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    box-sizing: border-box;
    height: 1.375rem;
    padding: 0 9px;
    border-radius: var(--ds-radius-full);
    border: var(--ds-border-width) solid var(--sky-color-border-strong);
    background: var(--ds-color-surface);
    font-family: var(--ds-font-mono);
    font-size: var(--ds-text-xs);
    line-height: 1;
    color: var(--ds-color-text-muted);
    white-space: nowrap;
  }
  .sky-harness-chip__dot {
    flex-shrink: 0;
    width: 7px;
    height: 7px;
    border-radius: 50%;
  }
</style>
