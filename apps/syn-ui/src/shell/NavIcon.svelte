<!--
  Line icons for the eight sections and the shell controls, drawn on a 16px
  grid exactly as the TopNav / PhoneDock boards draw them. currentColor only.
-->
<script lang="ts">
  type Name = 'overview' | 'workflows' | 'executions' | 'evals' | 'sessions' | 'artifacts' | 'triggers' | 'repos' | 'search' | 'play' | 'more' | 'home' | 'chevron' | 'close'
  let { name, size = 15 }: { name: Name; size?: number } = $props()
</script>

<svg
  class="sky-nav-icon"
  width={size}
  height={size}
  viewBox="0 0 16 16"
  fill={name === 'play' || name === 'more' ? 'currentColor' : 'none'}
  stroke={name === 'play' || name === 'more' ? 'none' : 'currentColor'}
  stroke-width={name === 'chevron' ? 1.75 : 1.5}
  stroke-linecap="round"
  stroke-linejoin="round"
  aria-hidden="true"
  focusable="false"
>
  {#if name === 'overview'}
    <path d="M2.5 2.5H7V7H2.5zM9 2.5h4.5V7H9zM2.5 9H7v4.5H2.5zM9 9h4.5v4.5H9z" />
  {:else if name === 'workflows'}
    <circle cx="4" cy="3.25" r="1.5" /><circle cx="4" cy="12.75" r="1.5" /><circle cx="12" cy="5" r="1.5" />
    <path d="M4 4.75v6.5M12 6.5c0 2.25-2 2.75-4 2.75S4 9.75 4 11" />
  {:else if name === 'executions'}
    <circle cx="8" cy="8" r="5.75" /><path d="M6.75 5.75l3.5 2.25-3.5 2.25z" />
  {:else if name === 'evals'}
    <path d="M6 1.75h4M6.75 1.75v4.1L3.1 12.4a1.25 1.25 0 0 0 1.1 1.85h7.6a1.25 1.25 0 0 0 1.1-1.85L9.25 5.85v-4.1M4.9 9.75h6.2" />
  {:else if name === 'sessions'}
    <path d="M1.75 8h2.5L6 3.5l3 9L10.75 8h3.5" />
  {:else if name === 'artifacts'}
    <path d="M4 1.75h5l3 3v9.5H4zM9 1.75v3h3" />
  {:else if name === 'triggers'}
    <path d="M8.75 1.75L3.5 9h4l-.75 5.25L12.5 7h-4z" />
  {:else if name === 'repos'}
    <path d="M3.5 12.25v-9a1.5 1.5 0 0 1 1.5-1.5h7.5v9H5a1.5 1.5 0 0 0 0 3h7.5v-3" />
  {:else if name === 'search'}
    <circle cx="7" cy="7" r="4.25" /><path d="M10.25 10.25L13.5 13.5" />
  {:else if name === 'play'}
    <path d="M4.5 2.75v10.5L13 8z" />
  {:else if name === 'more'}
    <circle cx="3.5" cy="8" r="1.4" /><circle cx="8" cy="8" r="1.4" /><circle cx="12.5" cy="8" r="1.4" />
  {:else if name === 'home'}
    <path d="M2.75 7.25L8 2.75l5.25 4.5V13a.5.5 0 0 1-.5.5H9.5V9.75h-3v3.75H3.25a.5.5 0 0 1-.5-.5z" />
  {:else if name === 'chevron'}
    <path d="M6 3.5L10.5 8 6 12.5" />
  {:else if name === 'close'}
    <path d="M4 4l8 8M12 4l-8 8" />
  {/if}
</svg>

<style>
  .sky-nav-icon {
    flex-shrink: 0;
    display: block;
  }
</style>
