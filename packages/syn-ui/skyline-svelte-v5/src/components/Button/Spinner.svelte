<!-- Busy glyph for buttons (CompActions "busy"): a track and a turning arc in currentColor. -->
<script lang="ts">
  let { size = 15 }: { size?: number } = $props()
</script>

<svg class="sky-spinner" width={size} height={size} viewBox="0 0 16 16" fill="none" aria-hidden="true" focusable="false">
  <circle cx="8" cy="8" r="6" stroke="currentColor" stroke-opacity="0.3" stroke-width="2" />
  <path d="M8 2a6 6 0 0 1 6 6" stroke="currentColor" stroke-width="2" stroke-linecap="round" />
</svg>

<style>
  .sky-spinner {
    flex-shrink: 0;
  }
  @media (prefers-reduced-motion: no-preference) {
    .sky-spinner {
      animation: sky-spin 0.8s linear infinite;
    }
  }
  @keyframes sky-spin {
    to {
      transform: rotate(360deg);
    }
  }
</style>
