// Type test for react-jsx.d.ts (tsc -p types/tsconfig.json; never bundled).
import type { JSX } from 'react'
import type {} from './react-jsx'

const verifiers = [{ name: 'claude-sonnet-5-5', colour: 2, scores: [48, 89], costs: [0.49, 0.52] }]

export const ok: JSX.Element[] = [
  <sky-s-mark size={26} label="Syntropic137" />,
  <sky-s-mark size="15%" animate slot="overlay" />,
  <sky-iso-city days={[{ date: '2026-10-08', sessions: 3 }]} live={[1]} animate drift cols={16} rows={8} cell={30} />,
  <sky-eval-explorer verifiers={verifiers} passAt={70} judge="claude-opus-5-5" selected={0} onverifierchange={(e) => e.detail.index} />,
  <sky-harness-chip provider="claude" label="implement · claude" />,
  <sky-harness-lanes phases={[{ name: 'plan', provider: 'claude', span: 2 }]} />,
  <sky-tool-log rows={[{ time: '14:02:11', tool: 'Read', target: 'a.py', duration: '42ms' }]} speed={1.75} />,
  <sky-usage-band tokens={{ cacheRead: 1, cacheWrite: 0, output: 1, input: 1 }} shape="flat" legend="compact" className="band" />,
]

// @ts-expect-error provider is required
export const missing = <sky-harness-chip label="x" />
// @ts-expect-error days must be SkylineDay[]
export const wrong = <sky-iso-city days={[1, 2]} />
