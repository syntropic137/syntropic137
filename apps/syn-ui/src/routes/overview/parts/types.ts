import type { ObjectKind } from '@syn137/skyline-core/patterns'

/** One card in the "From trigger to artifact" pipeline. */
export interface PipelineItem {
  kind: ObjectKind
  label: string
  /** Pre-formatted count ("…" while loading). */
  count: string
  /** Desktop sub-line. */
  sub: string
  /** Phone sub-line. */
  subShort: string
  /** App path, without the deploy base. */
  path: string
}
