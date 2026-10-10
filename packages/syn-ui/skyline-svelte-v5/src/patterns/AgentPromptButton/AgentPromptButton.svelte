<!--
  Agent Prompt Button (Workflow board): agents start runs, people copy the
  prompt. One primary button that copies a ready-to-paste prompt with the
  CLI command and the workflow's inputs, and a hint that confirms the copy.
  Full width in a narrow container.
-->
<script lang="ts">
  import { onDestroy } from 'svelte'
  import { GLYPH, buildAgentPrompt } from '@syn137/skyline-core/patterns'
  import { COPY_FEEDBACK_MS, copyFeedback, type CopyEvent, type CopyState } from '@syn137/skyline-core/state'
  import Glyph from '../Glyph/Glyph.svelte'
  import type { AgentPromptButtonProps } from './types'

  let {
    prompt,
    label = 'Copy agent prompt',
    copiedLabel = 'Prompt copied',
    hint = 'A ready-to-paste prompt with the CLI command and this workflow’s inputs.',
    copiedHint = 'Paste it into your agent to start a run.',
    oncopied,
    ...rest
  }: AgentPromptButtonProps = $props()

  const text = $derived(typeof prompt === 'string' ? prompt : buildAgentPrompt(prompt))
  let status = $state<CopyState>('idle')
  let timer: ReturnType<typeof setTimeout> | undefined

  function send(e: CopyEvent) {
    status = copyFeedback(status, e)
    if (status === 'copied' || status === 'failed') {
      clearTimeout(timer)
      timer = setTimeout(() => send({ type: 'reset' }), COPY_FEEDBACK_MS * 2)
    }
  }

  async function copy() {
    send({ type: 'copy' })
    try {
      await navigator.clipboard.writeText(text)
      send({ type: 'success' })
      oncopied?.(text)
    } catch {
      send({ type: 'error' })
    }
  }

  onDestroy(() => clearTimeout(timer))
</script>

<div {...rest} class="sky-agent-prompt">
  <div class="sky-agent-prompt__inner">
    <button class="sky-agent-prompt__button" type="button" data-state={status} onclick={copy} disabled={status === 'copying'}>
      <Glyph d={status === 'copied' ? GLYPH.check : GLYPH.copy} size={15} weight={1.6} />
      <span>{status === 'copied' ? copiedLabel : label}</span>
    </button>
    <span class="sky-agent-prompt__hint" role="status">
      {status === 'copied' ? copiedHint : status === 'failed' ? 'Copy failed: the browser blocked the clipboard.' : hint}
    </span>
  </div>
</div>

<style>
  .sky-agent-prompt {
    container-type: inline-size;
    min-width: 0;
    flex-grow: 1;
  }
  .sky-agent-prompt__inner {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-2-5);
  }
  .sky-agent-prompt__button {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 9px;
    height: 2.875rem;
    padding: 0 var(--ds-space-5);
    border: 0;
    border-radius: var(--sky-radius-row);
    background: var(--sky-color-accent-solid);
    box-shadow: var(--sky-shadow-glow);
    color: var(--sky-color-accent-solid-contrast);
    font: inherit;
    font-size: var(--sky-text-body);
    font-weight: var(--ds-font-weight-semibold);
    cursor: pointer;
  }
  .sky-agent-prompt__button:hover {
    background: color-mix(in oklab, var(--sky-color-accent-solid) 88%, var(--ds-color-accent-hover));
  }
  .sky-agent-prompt__button:focus-visible {
    outline: var(--sky-focus-ring-width) solid var(--sky-color-focus);
    outline-offset: var(--sky-focus-ring-offset);
  }
  .sky-agent-prompt__hint {
    font-size: var(--ds-text-sm);
    color: var(--ds-color-text-muted);
  }
  @container (min-width: 30rem) {
    .sky-agent-prompt__inner {
      flex-direction: row;
      flex-wrap: wrap;
      align-items: center;
      gap: var(--ds-space-2-5) var(--ds-space-3-5);
    }
    .sky-agent-prompt__button {
      height: 2.625rem;
      padding: 0 1.125rem;
      border-radius: 13px;
      font-size: 0.90625rem;
    }
  }
</style>
