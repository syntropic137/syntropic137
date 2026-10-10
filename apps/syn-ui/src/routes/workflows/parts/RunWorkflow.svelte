<!--
  Run workflow (Workflow board kickoff; React KickoffCard parity): the task,
  any other declared inputs, and Start. POST /workflows/{id}/execute through
  executeWorkflow(); the new run links to its execution page. A task that no
  phase prompt reads is refused before it is sent (#1280).
-->
<script lang="ts">
  import { canStartRun, consumesTask, type InputDeclarationLike } from '@syn137/skyline-core/screens/workflows'
  import { Button, Callout, Input, Textarea } from '@syn137/skyline-svelte-v5'
  import { ApiError, executeWorkflow, type ExecuteWorkflowResponse } from '@syn137/syn-ui-data'
  import { href } from '../../../lib/router'

  interface Props {
    workflowId: string
    declarations: InputDeclarationLike[]
    phases: { prompt_template?: string | null }[]
    onclose?: () => void
  }

  let { workflowId, declarations, phases, onclose }: Props = $props()

  let task = $state('')
  let inputs = $state<Record<string, string>>({})
  let sending = $state(false)
  let started = $state<ExecuteWorkflowResponse | null>(null)
  let failure = $state<string | null>(null)

  const extra = $derived(declarations.filter((d) => d.name !== 'task'))
  const taskDecl = $derived(declarations.find((d) => d.name === 'task'))
  const reads = $derived(consumesTask(phases))
  const discarded = $derived(task.trim() !== '' && !reads)
  const ready = $derived(!sending && !discarded && canStartRun(declarations, task, inputs))

  async function start(e: SubmitEvent) {
    e.preventDefault()
    if (!ready) return
    sending = true
    failure = null
    try {
      const values = Object.fromEntries(Object.entries(inputs).filter(([, v]) => v.trim() !== ''))
      started = await executeWorkflow(workflowId, { task: task.trim() || undefined, inputs: values })
      task = ''
    } catch (err) {
      failure = err instanceof ApiError ? (typeof err.detail === 'string' ? err.detail : `The server answered ${err.status}.`) : err instanceof Error ? err.message : String(err)
    } finally {
      sending = false
    }
  }
</script>

<form class="sky-wrun" aria-label="Run workflow" onsubmit={start}>
  <div class="sky-wrun__field">
    <label for="sky-wrun-task">Task{#if taskDecl?.required}<span aria-hidden="true"> *</span>{/if}</label>
    <Textarea id="sky-wrun-task" rows={3} placeholder="Describe what to work on" bind:value={task} required={taskDecl?.required ?? false} />
    {#if discarded}
      <span class="sky-wrun__hint" data-tone="danger">No phase prompt reads the task ($ARGUMENTS or &#123;&#123;task&#125;&#125;), so it would be discarded. Clear it to run the workflow as written.</span>
    {:else if taskDecl?.description}
      <span class="sky-wrun__hint">{taskDecl.description}. Fills $ARGUMENTS in the phase prompts.</span>
    {/if}
  </div>
  {#each extra as d (d.name)}
    <div class="sky-wrun__field">
      <label for={`sky-wrun-${d.name}`}>{d.name}{#if d.required}<span aria-hidden="true"> *</span>{/if}</label>
      <Input id={`sky-wrun-${d.name}`} placeholder={d.default ?? ''} bind:value={inputs[d.name]} />
      {#if d.description}<span class="sky-wrun__hint">{d.description}</span>{/if}
    </div>
  {/each}
  <div class="sky-wrun__actions">
    <Button type="submit" variant="solid" disabled={!ready}>{sending ? 'Starting…' : 'Start run'}</Button>
    {#if onclose}<Button type="button" variant="ghost" onclick={onclose}>Close</Button>{/if}
    {#if started}
      <span class="sky-wrun__done" role="status">Started <a href={href(`/executions/${encodeURIComponent(started.execution_id)}`)}>{started.execution_id}</a>{started.message ? `. ${started.message}` : ''}</span>
    {/if}
  </div>
  {#if failure}<Callout tone="danger" title="The run did not start." role="alert">{failure}</Callout>{/if}
</form>

<style>
  .sky-wrun {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-3-5);
    padding: var(--ds-space-5);
    border-radius: var(--sky-radius-xl);
    border: var(--ds-border-width) solid var(--sky-color-accent-ring);
    background: var(--ds-color-surface);
    box-shadow: var(--sky-shadow-raised);
  }
  .sky-wrun__field {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-1-5);
    min-width: 0;
  }
  .sky-wrun__field label {
    font-size: var(--ds-text-sm);
    font-weight: var(--ds-font-weight-semibold);
  }
  .sky-wrun__hint {
    font-size: var(--ds-text-xs);
    color: var(--ds-color-text-muted);
  }
  .sky-wrun__hint[data-tone='danger'] {
    color: var(--sky-color-danger-soft-fg);
  }
  .sky-wrun__actions {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--ds-space-2-5);
  }
  .sky-wrun__done {
    font-size: var(--ds-text-sm);
    color: var(--ds-color-text-muted);
  }
  .sky-wrun__done a {
    font-family: var(--ds-font-mono);
    color: var(--ds-color-fg);
  }
  .sky-wrun__done a:focus-visible {
    outline: var(--sky-focus-ring-width) solid var(--sky-color-focus);
    outline-offset: var(--sky-focus-ring-offset);
  }
</style>
