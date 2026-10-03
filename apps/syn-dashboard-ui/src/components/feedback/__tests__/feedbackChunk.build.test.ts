/**
 * The widget's JavaScript is absent from the default build (#105, ADR-016).
 *
 * `FeedbackMount.test.tsx` proves the widget does not RUN when the flag is
 * off. That is a weaker claim than the one the feature flag actually makes:
 * an open-source user "must not be able to tell the feature exists", and a
 * mounted-but-hidden component still ships 250 kB of widget and html2canvas
 * to every one of them, and still shows up in devtools.
 *
 * So this asserts the claim where it is decided — in the bundle. It runs a
 * real production build and walks the emitted chunk graph, because the thing
 * that guarantees the split is `React.lazy(() => import(...))` in
 * FeedbackMount, and nothing about that is visible to a test rendering into
 * jsdom: turn that dynamic import into a static one and every runtime test
 * still passes while every user starts downloading the widget.
 *
 * The assertion is over module ids rather than over minified code, since a
 * module id is what Rollup actually resolved and is not at the mercy of a
 * minifier keeping some string intact.
 */

// @vitest-environment node

import { fileURLToPath } from 'node:url'

import type { OutputAsset, OutputChunk, RollupOutput } from 'rollup'
import { build } from 'vite'
import { describe, expect, it } from 'vitest'

const DASHBOARD_ROOT = fileURLToPath(new URL('../../../..', import.meta.url))

/**
 * Modules that belong to the widget and to nothing else. `html2canvas` is the
 * screenshot dependency the widget pulls in and is the single largest reason
 * this split is worth having.
 */
const WIDGET_MODULE = /ui-feedback-react|FeedbackWidgetChunk|html2canvas/

/** A full production build takes ~20s in CI; `tsc` is not re-run here. */
const BUILD_TIMEOUT = 180_000

function isChunk(part: OutputChunk | OutputAsset): part is OutputChunk {
  return part.type === 'chunk'
}

/**
 * One build, shared. Both tests read the same chunk graph and neither
 * mutates it, so building twice would only cost another ~20s.
 */
let bundle: Promise<OutputChunk[]> | undefined

function buildDashboard(): Promise<OutputChunk[]> {
  bundle ??= runBuild()
  return bundle
}

async function runBuild(): Promise<OutputChunk[]> {
  const result = await build({
    root: DASHBOARD_ROOT,
    logLevel: 'silent',
    configFile: fileURLToPath(new URL('../../../../vite.config.ts', import.meta.url)),
    // Nothing is written: the claim is about what the build EMITS, and a test
    // that overwrites dist/ would silently change what a later `pnpm preview`
    // or a Docker build layer is serving.
    build: { write: false },
  })
  const outputs = (Array.isArray(result) ? result : [result]) as RollupOutput[]
  return outputs.flatMap((output) => output.output.filter(isChunk))
}

/**
 * Every chunk the browser is made to download before any user interaction:
 * the entry, plus everything it imports statically, transitively.
 *
 * Deliberately does NOT follow `dynamicImports` — that is precisely the edge
 * the feature flag is allowed to sit behind, because it is only traversed
 * when `FeedbackMount` decides the feature is on.
 */
function eagerlyLoadedChunks(chunks: OutputChunk[]): OutputChunk[] {
  const byFileName = new Map(chunks.map((chunk) => [chunk.fileName, chunk]))
  const reached = new Set<string>()
  const queue = chunks.filter((chunk) => chunk.isEntry).map((chunk) => chunk.fileName)

  while (queue.length > 0) {
    const fileName = queue.pop()!
    if (reached.has(fileName)) continue
    reached.add(fileName)
    queue.push(...(byFileName.get(fileName)?.imports ?? []))
  }

  return [...reached].map((fileName) => byFileName.get(fileName)!).filter(Boolean)
}

function widgetModulesIn(chunks: OutputChunk[]): string[] {
  return chunks.flatMap((chunk) => chunk.moduleIds.filter((id) => WIDGET_MODULE.test(id)))
}

describe('the default dashboard build', () => {
  it('ships no part of the feedback widget in the eagerly-loaded bundle', async () => {
    const chunks = await buildDashboard()
    const eager = eagerlyLoadedChunks(chunks)

    expect(eager.length).toBeGreaterThan(0)
    expect(widgetModulesIn(eager)).toEqual([])
  }, BUILD_TIMEOUT)

  it('still builds the widget, into a chunk only a dynamic import reaches', async () => {
    const chunks = await buildDashboard()
    const eager = new Set(eagerlyLoadedChunks(chunks).map((chunk) => chunk.fileName))

    // Without this the test above passes just as well for a build that has
    // dropped the widget altogether, which is a different bug, not a pass.
    const widgetChunks = chunks.filter((chunk) => widgetModulesIn([chunk]).length > 0)
    expect(widgetChunks.map((chunk) => chunk.fileName)).not.toEqual([])

    for (const chunk of widgetChunks) {
      expect(eager.has(chunk.fileName)).toBe(false)
    }

    // And it is reachable — from a dynamic import, which is the whole point.
    const dynamicTargets = new Set(chunks.flatMap((chunk) => chunk.dynamicImports))
    expect(widgetChunks.some((chunk) => dynamicTargets.has(chunk.fileName))).toBe(true)
  }, BUILD_TIMEOUT)
})
