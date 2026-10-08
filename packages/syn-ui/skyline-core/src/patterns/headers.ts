/**
 * Prop types for the small display patterns: Page Header, Lineage Trail,
 * Outcome Ring, Copy Button, Status Badge, Object Icon.
 */
import type { ObjectKind } from './types'

export interface Figure {
  /** Uppercase mono label: "Duration". */
  label: string
  /** Pre-formatted: "3m 47s", "$0.2100". */
  value: string
}

export interface PageHeaderProps {
  kind: ObjectKind
  title: string
  /** Mono line above the title: "exec-66e14f235942". */
  eyebrow?: string
  /** Small uppercase label right above the title: "Task". */
  titleLabel?: string
  description?: string
  /** Raw API status; draws a Status Badge in the meta row. */
  status?: string
  /** Text beside the status: "3 of 3 phases · Aug 27, 2026, 2:59 AM". */
  meta?: string
  figures?: readonly Figure[]
  /** Columns for the figures from 48rem (default 2). */
  figureColumns?: 2 | 3
}

export interface LineageStep {
  /** "Workflow", "Execution", "Phase", "Session". */
  kind: string
  /** Mono value: "research-workflow-v2". */
  value: string
  href?: string
}

export interface OutcomeCounts {
  completed: number
  failed: number
  cancelled: number
}

export type StatusBadgeShape = 'pill' | 'square' | 'glyph'
