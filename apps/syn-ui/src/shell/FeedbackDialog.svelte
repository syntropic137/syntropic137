<!--
  Feedback modal (#1385): type, priority, title, description and the current
  page URL, filed through createFeedback(). Loaded lazily by AppShell on the
  first click of a Feedback button.

  The API has no title field, so the title is the comment's first line and
  the description follows a blank line, which is how the React widget's
  tickets read in the list. No screenshot: the React widget captures one with
  html2canvas and uploads it as multipart, and neither belongs in Skyline
  (no new dependency; the data client sends JSON only).
-->
<script lang="ts">
  import { ApiError, FEEDBACK_PRIORITIES, FEEDBACK_TYPES, createFeedback, type FeedbackItem, type FeedbackPriority, type FeedbackType } from '@syn137/syn-ui-data'
  import { Button, Callout, Checkbox, Dialog, Input, Label, Select, Textarea } from '@syn137/skyline-svelte-v5'
  import { href, router } from '../lib/router'

  let { open = $bindable(false) }: { open?: boolean } = $props()

  const TYPE_LABEL = {
    bug: 'Bug',
    feature: 'Idea',
    ui_ux: 'UI/UX',
    performance: 'Performance',
    question: 'Question',
    other: 'Other',
  } as const satisfies Record<FeedbackType, string>
  const PRIORITY_LABEL = { low: 'Low', medium: 'Medium', high: 'High', critical: 'Critical' } as const satisfies Record<FeedbackPriority, string>

  const typeOptions = FEEDBACK_TYPES.map((value) => ({ value, label: TYPE_LABEL[value] }))
  const priorityOptions = FEEDBACK_PRIORITIES.map((value) => ({ value, label: PRIORITY_LABEL[value] }))

  type Phase = { kind: 'editing' } | { kind: 'sending' } | { kind: 'sent'; item: FeedbackItem } | { kind: 'failed'; message: string }

  let type = $state<FeedbackType>('bug')
  let priority = $state<FeedbackPriority>('medium')
  let title = $state('')
  let description = $state('')
  let includeUrl = $state(true)
  let phase = $state<Phase>({ kind: 'editing' })
  let titleTouched = $state(false)

  const titleMissing = $derived(title.trim() === '')
  const sending = $derived(phase.kind === 'sending')

  function isType(v: string): v is FeedbackType {
    return (FEEDBACK_TYPES as readonly string[]).includes(v)
  }
  function isPriority(v: string): v is FeedbackPriority {
    return (FEEDBACK_PRIORITIES as readonly string[]).includes(v)
  }

  function reset() {
    type = 'bug'
    priority = 'medium'
    title = ''
    description = ''
    includeUrl = true
    titleTouched = false
    phase = { kind: 'editing' }
  }

  function messageOf(e: unknown): string {
    if (e instanceof ApiError && e.status === 404) return 'Feedback is switched off on this API (SYN_UI_FEEDBACK_ENABLED).'
    if (e instanceof Error && e.message) return e.message
    return 'The feedback could not be sent.'
  }

  async function submit(e: SubmitEvent) {
    e.preventDefault()
    titleTouched = true
    if (titleMissing || sending) return
    phase = { kind: 'sending' }
    const comment = description.trim() ? `${title.trim()}\n\n${description.trim()}` : title.trim()
    try {
      const item = await createFeedback({
        url: includeUrl ? location.href : new URL(href('/'), location.origin).href,
        route: includeUrl ? router.path : undefined,
        viewport_width: innerWidth,
        viewport_height: innerHeight,
        feedback_type: type,
        priority,
        comment,
        app_name: 'syn-ui',
        user_agent: navigator.userAgent,
        environment: import.meta.env.DEV ? 'development' : import.meta.env.MODE,
        hostname: location.hostname,
      })
      phase = { kind: 'sent', item }
    } catch (err: unknown) {
      phase = { kind: 'failed', message: messageOf(err) }
    }
  }

  function onOpenChange(next: boolean) {
    // Reopening after a sent item starts a fresh form; a failed draft is kept.
    if (next && phase.kind === 'sent') reset()
  }
</script>

<Dialog bind:open {onOpenChange} title="Send feedback" description="Goes to the team's feedback queue with this page's URL." size="md">
  {#snippet children({ close })}
    {#if phase.kind === 'sent'}
      <div class="sky-feedback__done" role="status">
        <Callout tone="note" title="Thanks, feedback sent.">
          Filed as <code class="sky-feedback__id">{phase.item.id}</code>.
        </Callout>
        <div class="sky-feedback__actions">
          <Button variant="outline" onclick={reset}>Send another</Button>
          <Button onclick={close}>Done</Button>
        </div>
      </div>
    {:else}
      <form class="sky-feedback" onsubmit={submit} novalidate aria-busy={sending}>
        <div class="sky-feedback__row">
          <div class="sky-feedback__field">
            <Label for="sky-feedback-type">Type</Label>
            <Select id="sky-feedback-type" options={typeOptions} value={type} onValueChange={(v: string) => { if (isType(v)) type = v }} disabled={sending} />
          </div>
          <div class="sky-feedback__field">
            <Label for="sky-feedback-priority">Priority</Label>
            <Select id="sky-feedback-priority" options={priorityOptions} value={priority} onValueChange={(v: string) => { if (isPriority(v)) priority = v }} disabled={sending} />
          </div>
        </div>
        <div class="sky-feedback__field">
          <Label for="sky-feedback-title" required>Title</Label>
          <Input
            id="sky-feedback-title"
            bind:value={title}
            maxlength={200}
            autocomplete="off"
            placeholder="What happened, in one line"
            disabled={sending}
            onblur={() => (titleTouched = true)}
            invalid={titleTouched && titleMissing}
            message={titleTouched && titleMissing ? 'Add a title.' : undefined}
            messageTone="danger"
          />
        </div>
        <div class="sky-feedback__field">
          <Label for="sky-feedback-description" hint="optional">Description</Label>
          <Textarea id="sky-feedback-description" bind:value={description} rows={5} placeholder="Steps, what you expected, what you saw" disabled={sending} />
        </div>
        <Checkbox checked={includeUrl} onCheckedChange={(c: boolean | 'indeterminate') => (includeUrl = c === true)} disabled={sending}>
          Include this page's URL
        </Checkbox>
        {#if phase.kind === 'failed'}
          <Callout tone="danger" role="alert" title="Not sent.">{phase.message}</Callout>
        {/if}
        <div class="sky-feedback__actions">
          <Button type="button" variant="ghost" onclick={close} disabled={sending}>Cancel</Button>
          <Button type="submit" loading={sending}>{sending ? 'Sending' : 'Send feedback'}</Button>
        </div>
      </form>
    {/if}
  {/snippet}
</Dialog>

<style>
  .sky-feedback,
  .sky-feedback__done {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-4);
  }
  .sky-feedback__row {
    display: grid;
    grid-template-columns: 1fr;
    gap: var(--ds-space-4);
  }
  .sky-feedback__field {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-2);
    min-width: 0;
  }
  .sky-feedback__actions {
    display: flex;
    flex-wrap: wrap;
    justify-content: flex-end;
    gap: var(--ds-space-2-5);
  }
  .sky-feedback__id {
    font-family: var(--ds-font-mono);
    font-size: var(--sky-text-label);
    overflow-wrap: anywhere;
  }
  @media (min-width: 48rem) {
    .sky-feedback__row {
      grid-template-columns: 1fr 1fr;
    }
  }
</style>
