<!-- Syntropic137 wordmark: the 3D cube (faces from skyline-core's extrude recipe) and Orbitron type. -->
<script lang="ts">
  import { extrudeColors } from '@syn137/skyline-core/geometry'

  let { href = '/', compact = false }: { href?: string; compact?: boolean } = $props()
  const faces = extrudeColors('var(--ds-color-accent)', { light: 'var(--ds-color-fg)', topMix: 62, sideMix: 55 })
</script>

<a class="sky-wordmark" data-compact={compact || undefined} {href} aria-label="Syntropic137 overview">
  <svg width="26" height="26" viewBox="0 0 24 24" aria-hidden="true">
    <polygon points="12,3 21,7.5 12,12 3,7.5" style:fill={faces.top} />
    <polygon points="3,7.5 12,12 12,21.5 3,17" style:fill={faces.front} />
    <polygon points="12,12 21,7.5 21,17 12,21.5" style:fill={faces.side} />
  </svg>
  <span class="sky-wordmark__text">Syntropic<span class="sky-wordmark__num">137</span></span>
</a>

<style>
  .sky-wordmark {
    display: flex;
    align-items: center;
    gap: var(--ds-space-2-5);
    min-height: var(--sky-size-touch);
    border-radius: var(--ds-radius-md);
    text-decoration: none;
    color: var(--ds-color-fg);
  }
  .sky-wordmark:focus-visible {
    outline: var(--sky-focus-ring-width) solid var(--sky-color-focus);
    outline-offset: var(--sky-focus-ring-offset);
  }
  .sky-wordmark__text {
    font-family: var(--sky-font-brand);
    font-size: var(--ds-text-sm);
    font-weight: var(--ds-font-weight-semibold);
    letter-spacing: var(--sky-tracking-brand);
    white-space: nowrap;
  }
  .sky-wordmark__num {
    color: var(--ds-color-accent);
  }
  @media (min-width: 48rem) {
    .sky-wordmark__text {
      font-size: var(--ds-text-md);
    }
  }
</style>
