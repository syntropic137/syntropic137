/**
 * Live event streams over SSE.
 *
 * One EventSource per URL per tab, shared by every subscriber (refcounted:
 * opens on the first subscribe, closes on the last unsubscribe). Each
 * subscriber receives frames in batches, at most once per animation frame.
 *
 * Reconnects (#1924). EventSource retries a dropped connection on its own,
 * but an HTTP error on a retry (the API restarting for a deploy, a 502/524
 * from the edge) closes it for good, and a long-open tab then never updates
 * again. The hub reopens a closed source with backoff while anyone still
 * subscribes. Either way, frames sent while disconnected are gone, so every
 * reconnect calls `onReconnect`: subscribers refetch instead of trusting
 * a view that missed events.
 *
 * In fixtures mode nothing connects; subscribers see state 'fixtures'.
 */
import { clientConfig } from '../client/config'
import type { SSEEventFrame } from '../types'
import { type Scheduler, createFrameBatcher, frameScheduler } from './frameBatcher'

export type StreamState = 'connecting' | 'open' | 'closed' | 'fixtures'

export interface StreamSubscriber {
  /** Frames since the last delivery, oldest first. */
  onFrames?: (frames: SSEEventFrame[]) => void
  /** Only frames whose event_type passes are delivered. A throwing filter counts as false. */
  filter?: (eventType: string) => boolean
  onState?: (state: StreamState) => void
  /** The stream came back after a disconnect; frames sent in between were missed. */
  onReconnect?: () => void
}

/** The subset of EventSource the hub uses; injectable for tests. */
export interface EventSourceLike {
  onopen: ((ev: Event) => unknown) | null
  onerror: ((ev: Event) => unknown) | null
  onmessage: ((ev: MessageEvent<string>) => unknown) | null
  readyState: number
  close(): void
}
export type EventSourceFactory = (url: string) => EventSourceLike

interface Channel {
  source: EventSourceLike | null
  state: StreamState
  subs: Set<Sub>
  lastEventAt: number | null
  /** Has opened at least once, so the next open is a reconnect. */
  opened: boolean
  /** Reopens since the last successful open; drives the backoff. */
  attempts: number
  retry: ReturnType<typeof setTimeout> | undefined
}

interface Sub {
  spec: StreamSubscriber
  batcher: ReturnType<typeof createFrameBatcher<SSEEventFrame>>
}

const passes = (spec: StreamSubscriber, eventType: string) => {
  if (!spec.filter) return true
  try {
    return spec.filter(eventType)
  } catch {
    return false
  }
}

export class LiveHub {
  private channels = new Map<string, Channel>()

  constructor(
    private readonly options: {
      createSource?: EventSourceFactory
      schedule?: Scheduler
      fixtures?: () => boolean
      /** Wait before reopening a closed source, by attempt (0-based). Default 1s doubling to 30s. */
      reconnectDelayMs?: (attempt: number) => number
    } = {},
  ) {}

  subscribe(url: string, spec: StreamSubscriber): () => void {
    let ch = this.channels.get(url)
    if (!ch) {
      ch = { source: null, state: 'connecting', subs: new Set(), lastEventAt: null, opened: false, attempts: 0, retry: undefined }
      this.channels.set(url, ch)
    }
    const channel = ch
    const sub: Sub = {
      spec,
      batcher: createFrameBatcher((frames) => {
        try {
          spec.onFrames?.(frames)
        } catch {
          // one consumer's error never tears down the stream
        }
      }, this.options.schedule ?? frameScheduler),
    }
    if (!channel.source && channel.subs.size === 0) this.open(url, channel)
    channel.subs.add(sub)
    spec.onState?.(channel.state)

    return () => {
      sub.batcher.cancel()
      channel.subs.delete(sub)
      if (channel.subs.size === 0) {
        clearTimeout(channel.retry)
        channel.source?.close()
        this.channels.delete(url)
      }
    }
  }

  /** Current state of a URL's stream ('closed' when nobody subscribes). */
  state(url: string): StreamState {
    return this.channels.get(url)?.state ?? 'closed'
  }

  lastEventAt(url: string): number | null {
    return this.channels.get(url)?.lastEventAt ?? null
  }

  private setState(channel: Channel, state: StreamState) {
    if (channel.state === state) return
    channel.state = state
    for (const s of channel.subs) s.spec.onState?.(state)
  }

  private open(url: string, channel: Channel) {
    const fixtures = this.options.fixtures?.() ?? clientConfig().fixtures
    const factory = this.options.createSource ?? defaultFactory()
    if (fixtures || !factory) {
      this.setState(channel, fixtures ? 'fixtures' : 'closed')
      return
    }
    const source = factory(url)
    channel.source = source
    source.onopen = () => {
      const reconnect = channel.opened
      channel.opened = true
      channel.attempts = 0
      this.setState(channel, 'open')
      if (reconnect) for (const s of channel.subs) safely(() => s.spec.onReconnect?.())
    }
    source.onerror = () => {
      // EventSource retries on its own; CONNECTING (0) after an error means it will.
      if (source.readyState === 0) return this.setState(channel, 'connecting')
      // CLOSED (2): it has given up. Reopen while anyone still listens.
      source.close()
      if (channel.source === source) channel.source = null
      this.setState(channel, 'closed')
      if (channel.subs.size === 0 || channel.retry) return
      const delay = (this.options.reconnectDelayMs ?? backoff)(channel.attempts++)
      channel.retry = setTimeout(() => {
        channel.retry = undefined
        if (channel.subs.size > 0 && !channel.source) {
          this.setState(channel, 'connecting')
          this.open(url, channel)
        }
      }, delay)
    }
    source.onmessage = (e) => {
      let frame: SSEEventFrame
      try {
        frame = JSON.parse(e.data) as SSEEventFrame
      } catch {
        return // malformed frame
      }
      channel.lastEventAt = Date.now()
      for (const s of channel.subs) if (passes(s.spec, frame.event_type)) s.batcher.push(frame)
    }
  }
}

const backoff = (attempt: number) => Math.min(30_000, 1000 * 2 ** attempt)

const safely = (run: () => void) => {
  try {
    run()
  } catch {
    // one consumer's error never tears down the stream
  }
}

function defaultFactory(): EventSourceFactory | null {
  if (typeof EventSource === 'undefined') return null
  return (url) => new EventSource(url)
}

/** The tab-wide hub. */
export const liveHub = new LiveHub()

/** Subscribe to the global activity feed (`/sse/activity`). */
export function subscribeActivity(spec: StreamSubscriber): () => void {
  return liveHub.subscribe(`${clientConfig().baseUrl}/sse/activity`, spec)
}

/** Subscribe to one execution's events (`/sse/executions/{id}`). */
export function subscribeExecution(executionId: string, spec: StreamSubscriber): () => void {
  return liveHub.subscribe(`${clientConfig().baseUrl}/sse/executions/${encodeURIComponent(executionId)}`, spec)
}
