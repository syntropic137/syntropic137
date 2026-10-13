/**
 * Provenance Strip and Run Tiles (Execution board, CompPatterns sheet).
 */

export interface ProvenanceCounts {
  platformSessions?: number | null
  nativeTranscripts?: number | null
  invocations?: number | null
  gaps?: number | null
}

const count = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`

/** "3 platform sessions · 0 native transcripts · 0 invocations · 1 gap". Unknown counts are left out. */
export function provenanceSummary(c: ProvenanceCounts): string {
  const parts: string[] = []
  if (typeof c.platformSessions === 'number') parts.push(count(c.platformSessions, 'platform session', 'platform sessions'))
  if (typeof c.nativeTranscripts === 'number') parts.push(count(c.nativeTranscripts, 'native transcript', 'native transcripts'))
  if (typeof c.invocations === 'number') parts.push(count(c.invocations, 'invocation', 'invocations'))
  if (typeof c.gaps === 'number') parts.push(count(c.gaps, 'gap', 'gaps'))
  return parts.join(' · ')
}

export interface ProvenanceStripProps {
  title?: string
  counts: ProvenanceCounts
  /** The coverage warning: bold lead, then the rest. */
  warning?: { lead: string; body?: string } | null
  /** Plain note under the warning. */
  note?: string | null
  /** Mono facts: "revision f823…b742d4d5", "remote replication off". */
  facts?: readonly string[]
  /** Button label; the screen passes the handler. */
  actionLabel?: string | null
}

export interface RunTileSession {
  /** Short id: "10dfeb5d". */
  id: string
  /** "platform session · no local transcript". */
  note?: string
  href?: string
}

export interface RunTileArtifact {
  name: string
  /** "2.9 KB". */
  size?: string
  href?: string
}

export interface RunTilesProps {
  /** The phase name, for accessible labels. */
  phase?: string
  session?: RunTileSession | null
  artifact?: RunTileArtifact | null
}
