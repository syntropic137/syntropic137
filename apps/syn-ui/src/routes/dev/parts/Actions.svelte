<!-- /dev/components, board CompActions: buttons, copy, toggles, switches, checkboxes and fields. -->
<script lang="ts">
  import Copy from '@lucide/svelte/icons/copy'
  import Search from '@lucide/svelte/icons/search'
  import Trash from '@lucide/svelte/icons/trash-2'
  import {
    Button,
    Checkbox,
    CopyButton,
    Input,
    Label,
    Select,
    Switch,
    Tag,
    Textarea,
    Toggle,
    ToggleGroup,
  } from '@syn137/skyline-svelte-v5'

  let expanded = $state(false)
  let view = $state<string[]>(['rendered'])
  let range = $state<string[]>(['16w'])
  let status = $state<string[]>(['all'])
  let tagOn = $state(true)
  let sort = $state('most-run')
  let search = $state('')
  let count = $state('0')
  let task = $state('')
</script>

<section class="demo" aria-labelledby="demo-button">
  <header>
    <h3 id="demo-button">Button</h3>
    <p class="demo__contract">ButtonContract · required</p>
    <p>Primary for the one action a screen is for; secondary and ghost for the rest.</p>
  </header>
  <div class="demo__row">
    <figure><Button variant="solid">{#snippet icon()}<Copy size={16} />{/snippet}Copy agent prompt</Button><figcaption>primary</figcaption></figure>
    <figure><Button variant="outline">View transcript</Button><figcaption>secondary</figcaption></figure>
    <figure><Button variant="ghost">Expand all</Button><figcaption>ghost</figcaption></figure>
    <figure><Button variant="outline" tone="danger">Delete</Button><figcaption>danger</figcaption></figure>
    <figure><Button variant="ghost" aria-label="Delete">{#snippet icon()}<Trash size={16} />{/snippet}</Button><figcaption>icon only</figcaption></figure>
  </div>
  <div class="demo__row">
    <figure><Button variant="solid" disabled>Copy agent prompt</Button><figcaption>disabled</figcaption></figure>
    <figure><Button variant="solid" loading>Loading</Button><figcaption>busy</figcaption></figure>
    <figure><Button variant="solid" size="sm">Run</Button><figcaption>sm · 32px</figcaption></figure>
    <figure><Button variant="solid" size="md">Run</Button><figcaption>md · 36px</figcaption></figure>
    <figure><Button variant="solid" size="lg">Run</Button><figcaption>lg · 44px</figcaption></figure>
  </div>
  <div class="demo__row">
    <figure class="demo__wide"><Button variant="solid" size="lg" block>Copy agent prompt</Button><figcaption>phone, full width</figcaption></figure>
  </div>
</section>

<section class="demo" aria-labelledby="demo-copy">
  <header>
    <h3 id="demo-copy">Copy Button</h3>
    <p class="demo__contract">pattern · Button</p>
    <p>Copies one part or the whole list, then shows a check for two seconds.</p>
  </header>
  <div class="demo__row">
    <figure><CopyButton text="exec-66e14f235942" /><figcaption>idle</figcaption></figure>
    <figure><CopyButton text="all" label="Copy all" copiedLabel="Copied all" size="sm" /><figcaption>section</figcaption></figure>
    <figure><span class="demo__path">/workspace/skills-lock.json <CopyButton text="/workspace/skills-lock.json" size="xs" /></span><figcaption>on an output</figcaption></figure>
  </div>
</section>

<section class="demo" aria-labelledby="demo-toggle">
  <header>
    <h3 id="demo-toggle">Toggle and Toggle Group</h3>
    <p class="demo__contract">ToggleContract · ToggleGroupContract</p>
    <p>A lone pressed state, a segmented choice, or filter chips with counts.</p>
  </header>
  <div class="demo__row">
    <figure><Toggle pressed={expanded} onPressedChange={(p) => (expanded = p)}>Expand all</Toggle><figcaption>toggle {expanded ? 'on' : 'off'}</figcaption></figure>
    <figure><Toggle defaultPressed>Expand all</Toggle><figcaption>toggle on</figcaption></figure>
    <figure><Toggle disabled>Expand all</Toggle><figcaption>disabled</figcaption></figure>
  </div>
  <div class="demo__row">
    <figure>
      <ToggleGroup type="single" aria-label="View" items={[{ value: 'rendered', label: 'Rendered' }, { value: 'raw', label: 'Raw' }]} value={view} onValueChange={(v) => (view = v)} />
      <figcaption>segmented</figcaption>
    </figure>
    <figure>
      <ToggleGroup type="single" mono aria-label="Range" items={[{ value: '16w', label: '16w' }, { value: 'year', label: 'Year' }]} value={range} onValueChange={(v) => (range = v)} />
      <figcaption>segmented, mono</figcaption>
    </figure>
  </div>
  <div class="demo__row">
    <figure class="demo__wide">
      <ToggleGroup
        type="single"
        variant="chips"
        aria-label="Status"
        items={[{ value: 'all', label: 'All', count: 75 }, { value: 'completed', label: 'Completed', count: 50 }, { value: 'failed', label: 'Failed', count: 23 }]}
        value={status}
        onValueChange={(v) => (status = v)}
      />
      <figcaption>filter chips</figcaption>
    </figure>
    <figure>
      {#if tagOn}<Tag variant="accent" onremove={() => (tagOn = false)} removeLabel="Clear tag filter">case:codex-cost-limit</Tag>{:else}<Button variant="ghost" size="sm" onclick={() => (tagOn = true)}>Restore</Button>{/if}
      <figcaption>removable tag filter</figcaption>
    </figure>
  </div>
</section>

<section class="demo" aria-labelledby="demo-switch">
  <header>
    <h3 id="demo-switch">Switch and Checkbox</h3>
    <p class="demo__contract">SwitchRootContract · CheckboxRootContract</p>
    <p>Switch for a live setting such as a trigger; checkbox for selecting rows.</p>
  </header>
  <div class="demo__row">
    <figure><Switch defaultChecked aria-label="Trigger on" /><figcaption>on</figcaption></figure>
    <figure><Switch aria-label="Trigger off" /><figcaption>off</figcaption></figure>
    <figure><Switch disabled aria-label="Trigger disabled" /><figcaption>disabled</figcaption></figure>
  </div>
  <div class="demo__row">
    <figure><Checkbox aria-label="Row unchecked" /><figcaption>unchecked</figcaption></figure>
    <figure><Checkbox defaultChecked aria-label="Row checked" /><figcaption>checked</figcaption></figure>
    <figure><Checkbox checked="indeterminate" aria-label="Some rows" /><figcaption>some rows</figcaption></figure>
    <figure><Checkbox disabled aria-label="Row disabled" /><figcaption>disabled</figcaption></figure>
  </div>
</section>

<section class="demo" aria-labelledby="demo-input">
  <header>
    <h3 id="demo-input">Input, Select, Label</h3>
    <p class="demo__contract">InputContract · SelectRootContract · LabelContract</p>
    <p>Fields sit on the ground colour; the label states what is required.</p>
  </header>
  <div class="demo__fields">
    <Input type="search" placeholder="Search workflows" aria-label="Search" bind:value={search}>
      {#snippet leading()}<Search size={16} />{/snippet}
    </Input>
    <Select
      label="Sort"
      aria-label="Sort"
      options={[{ value: 'most-run', label: 'Most run' }, { value: 'name', label: 'Name' }]}
      value={sort}
      onValueChange={(v) => (sort = v)}
    />
    <Input aria-label="Max runs" inputmode="numeric" bind:value={count} invalid message="Must be at least 1." messageTone="danger" />
    <div class="demo__field">
      <Label for="demo-task" required hint="A phase prompt uses the task. Left empty, it renders blank.">Task · $ARGUMENTS</Label>
      <Textarea id="demo-task" rows={3} placeholder="Describe the task" bind:value={task} />
    </div>
  </div>
</section>

<style>
  .demo {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-4);
    min-width: 0;
    padding: var(--ds-space-5);
    border-radius: var(--sky-radius-xl);
    border: var(--ds-border-width) solid var(--ds-color-border);
    background: var(--ds-color-surface);
  }
  .demo header {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-1);
  }
  .demo h3 {
    margin: 0;
    font-size: var(--ds-text-lg);
    font-weight: var(--ds-font-weight-semibold);
  }
  .demo p {
    margin: 0;
    font-size: var(--ds-text-sm);
    color: var(--ds-color-text-muted);
  }
  .demo .demo__contract {
    font-family: var(--ds-font-mono);
    font-size: var(--ds-text-xs);
    color: var(--ds-color-text-subtle);
  }
  .demo__row {
    display: flex;
    flex-wrap: wrap;
    align-items: flex-end;
    gap: var(--ds-space-4) var(--ds-space-5);
  }
  figure {
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    gap: var(--ds-space-2);
    margin: 0;
    min-width: 0;
  }
  .demo__wide {
    flex: 1 1 100%;
    align-items: stretch;
  }
  figcaption {
    font-family: var(--ds-font-mono);
    font-size: var(--ds-text-xs);
    color: var(--ds-color-text-subtle);
  }
  .demo__path {
    display: inline-flex;
    align-items: center;
    gap: var(--ds-space-2);
    font-family: var(--ds-font-mono);
    font-size: var(--ds-text-xs);
    color: var(--sky-color-text-code);
    overflow-wrap: anywhere;
  }
  .demo__fields,
  .demo__field {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-3);
  }
  .demo__field {
    gap: var(--ds-space-1-5);
  }
</style>
