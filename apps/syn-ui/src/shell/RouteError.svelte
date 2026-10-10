<!-- Shown when a route's chunk fails to load (offline, or a deploy replaced the chunk). -->
<script lang="ts">
  let { error }: { error: unknown } = $props()
  const message = $derived(error instanceof Error ? error.message : String(error))
</script>

<section class="sky-route-error" role="alert">
  <h1>This page did not load</h1>
  <p>{message}</p>
  <button type="button" onclick={() => location.reload()}>Reload</button>
</section>

<style>
  .sky-route-error {
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    gap: var(--ds-space-3);
    padding: var(--ds-space-6);
    border-radius: var(--sky-radius-xl);
    border: var(--ds-border-width) solid var(--ds-color-border);
    background: var(--ds-color-surface);
  }
  h1 {
    margin: 0;
    font-size: var(--ds-text-xl);
  }
  p {
    margin: 0;
    color: var(--ds-color-text-muted);
    font-family: var(--ds-font-mono);
    font-size: var(--sky-text-data);
  }
  button {
    min-height: var(--sky-size-control-md);
    padding: 0 var(--ds-space-3-5);
    border-radius: var(--ds-radius-lg);
    border: var(--ds-border-width) solid var(--sky-color-border-strong);
    background: var(--sky-color-control);
    color: var(--ds-color-fg);
    cursor: pointer;
  }
  button:focus-visible {
    outline: var(--sky-focus-ring-width) solid var(--sky-color-focus);
    outline-offset: var(--sky-focus-ring-offset);
  }
  @media (pointer: coarse) {
    button {
      min-height: var(--sky-size-touch);
    }
  }
</style>
