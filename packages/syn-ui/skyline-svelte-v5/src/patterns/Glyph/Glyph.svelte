<!--
  A line glyph from skyline-core's GLYPH / STATUS_GLYPH_PATHS (16-unit grid).
  Internal to the patterns: decorative, inherits currentColor.
-->
<script lang="ts">
  let { d, size = 14, weight = 1.6 }: { d: string; size?: number; weight?: number } = $props()
</script>

<svg
  class="sky-glyph"
  width={size}
  height={size}
  viewBox="0 0 16 16"
  fill="none"
  stroke="currentColor"
  stroke-width={weight}
  stroke-linecap="round"
  stroke-linejoin="round"
  aria-hidden="true"
  focusable="false"><path {d} /></svg>

<style>
  .sky-glyph {
    flex-shrink: 0;
    display: block;
  }
</style>
