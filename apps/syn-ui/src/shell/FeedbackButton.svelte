<!--
  Feedback button for the shell navs (#1385). Renders nothing until the API
  says `ui_feedback` is on, and never outside a developer machine
  (FEEDBACK_LOCAL_ONLY). Opens the lazily loaded FeedbackDialog in AppShell.
-->
<script lang="ts">
  import MessageSquare from '@lucide/svelte/icons/message-square'
  import { getFeatures } from '@syn137/syn-ui-data'
  import { resource } from '../lib/load.svelte'
  import { FEEDBACK_LOCAL_ONLY, feedbackUi, openFeedback } from './feedback.svelte'

  let { compact = false }: { compact?: boolean } = $props()

  const features = resource((signal) => (FEEDBACK_LOCAL_ONLY ? getFeatures(signal) : Promise.resolve({ ui_feedback: false })))
  const enabled = $derived(FEEDBACK_LOCAL_ONLY && features.data?.ui_feedback === true)
</script>

{#if enabled}
  <button
    class="sky-feedback-btn"
    type="button"
    data-compact={compact || undefined}
    aria-label="Send feedback"
    aria-haspopup="dialog"
    aria-expanded={feedbackUi.open}
    onclick={openFeedback}
  >
    <MessageSquare size={compact ? 17 : 14} aria-hidden="true" />
    {#if !compact}<span>Feedback</span>{/if}
  </button>
{/if}

<style>
  .sky-feedback-btn {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: var(--ds-space-2);
    height: var(--sky-size-nav-item);
    padding: 0 var(--ds-space-2-5);
    border-radius: var(--ds-radius-md);
    border: var(--ds-border-width) solid var(--ds-color-border);
    background: var(--sky-color-control);
    color: var(--ds-color-text-muted);
    font: inherit;
    cursor: pointer;
  }
  .sky-feedback-btn[data-compact] {
    width: var(--sky-size-touch);
    height: var(--sky-size-touch);
    padding: 0;
    border-radius: var(--sky-radius-row);
  }
  .sky-feedback-btn:hover {
    border-color: var(--sky-color-border-hover);
    color: var(--ds-color-fg);
  }
  .sky-feedback-btn:focus-visible {
    outline: var(--sky-focus-ring-width) solid var(--sky-color-focus);
    outline-offset: var(--sky-focus-ring-offset);
  }
  @media (pointer: coarse) {
    .sky-feedback-btn {
      min-height: var(--sky-size-touch);
    }
  }
</style>
