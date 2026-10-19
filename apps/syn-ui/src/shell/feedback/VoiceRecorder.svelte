<!--
  Record one voice note (React widget parity): Record, a running timer, Stop,
  then playback and Delete. Permission denied and unsupported browsers say so.
-->
<script lang="ts">
  import Mic from '@lucide/svelte/icons/mic'
  import Square from '@lucide/svelte/icons/square'
  import Trash2 from '@lucide/svelte/icons/trash'
  import { Button } from '@syn137/skyline-svelte-v5'
  import { onDestroy } from 'svelte'
  import { formatDuration, supportedVoiceMime, voiceError, voiceSupported, type VoiceNote } from './voice'

  let { note = $bindable(null), disabled = false }: { note?: VoiceNote | null; disabled?: boolean } = $props()

  let recorder: MediaRecorder | null = null
  let stream: MediaStream | null = null
  let timer: ReturnType<typeof setInterval> | undefined
  let recording = $state(false)
  let seconds = $state(0)
  let error = $state<string | null>(null)
  const supported = voiceSupported()

  async function start() {
    error = null
    if (!supported) {
      error = 'Voice recording is not supported in this browser.'
      return
    }
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      const mime = supportedVoiceMime()
      const rec = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined)
      const chunks: Blob[] = []
      rec.ondataavailable = (e) => {
        if (e.data.size > 0) chunks.push(e.data)
      }
      rec.onstop = () => {
        const blob = new Blob(chunks, { type: rec.mimeType || mime || 'audio/webm' })
        if (note) URL.revokeObjectURL(note.url)
        note = { blob, url: URL.createObjectURL(blob), seconds }
        release()
      }
      rec.onerror = () => {
        error = 'Recording failed.'
        stop()
      }
      recorder = rec
      rec.start(100)
      seconds = 0
      recording = true
      timer = setInterval(() => (seconds += 1), 1000)
    } catch (e: unknown) {
      error = voiceError(e)
      release()
    }
  }

  function stop() {
    clearInterval(timer)
    recording = false
    if (recorder && recorder.state !== 'inactive') recorder.stop()
    else release()
  }

  function release() {
    stream?.getTracks().forEach((t) => t.stop())
    stream = null
    recorder = null
  }

  function remove() {
    if (note) URL.revokeObjectURL(note.url)
    note = null
  }

  onDestroy(() => {
    clearInterval(timer)
    if (recorder && recorder.state !== 'inactive') {
      recorder.onstop = null
      recorder.stop()
    }
    release()
  })
</script>

<div class="sky-fb-voice" data-testid="feedback-voice">
  {#if recording}
    <Button size="sm" variant="outline" tone="danger" onclick={stop}>
      {#snippet icon()}<Square size={14} aria-hidden="true" />{/snippet}
      Stop
    </Button>
    <span class="sky-fb-voice__rec" role="status" aria-live="polite"><span class="sky-fb-voice__dot" aria-hidden="true"></span>Recording {formatDuration(seconds)}</span>
  {:else if note}
    <audio class="sky-fb-voice__audio" controls src={note.url} aria-label="Voice note"></audio>
    <span class="sky-fb-voice__time">{formatDuration(note.seconds)}</span>
    <Button size="sm" variant="ghost" aria-label="Delete voice note" onclick={remove} {disabled}>
      {#snippet icon()}<Trash2 size={14} aria-hidden="true" />{/snippet}
    </Button>
  {:else}
    <Button size="sm" variant="outline" onclick={start} {disabled}>
      {#snippet icon()}<Mic size={14} aria-hidden="true" />{/snippet}
      Record voice
    </Button>
  {/if}
  {#if error}<p class="sky-fb-voice__error" role="alert">{error}</p>{/if}
</div>

<style>
  .sky-fb-voice {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--ds-space-2);
  }
  .sky-fb-voice__rec {
    display: inline-flex;
    align-items: center;
    gap: var(--ds-space-1-5);
    font-family: var(--ds-font-mono);
    font-size: var(--sky-text-data);
    color: var(--ds-color-fg);
  }
  .sky-fb-voice__dot {
    width: var(--ds-space-2);
    height: var(--ds-space-2);
    border-radius: 50%;
    background: var(--ds-color-danger);
  }
  @media (prefers-reduced-motion: no-preference) {
    .sky-fb-voice__dot {
      animation: sky-fb-pulse 1.2s var(--sky-ease-in-out) infinite;
    }
  }
  @keyframes sky-fb-pulse {
    50% {
      opacity: 0.35;
    }
  }
  .sky-fb-voice__audio {
    height: var(--sky-size-control-sm);
    max-width: 100%;
  }
  .sky-fb-voice__time {
    font-family: var(--ds-font-mono);
    font-size: var(--sky-text-data);
    color: var(--ds-color-text-muted);
  }
  .sky-fb-voice__error {
    flex-basis: 100%;
    margin: 0;
    color: var(--ds-color-danger);
    font-size: var(--ds-text-sm);
  }
</style>
