import type { HTMLAttributes } from 'svelte/elements'
import type { ContractTone, ProgressContract } from '@syn137/skyline-core/contracts'

/**
 * Progress (ProgressContract): a running execution. CompDisplay draws it as
 * one block per phase ("phase 2 of 3"): pass `segments` for that, with
 * `value` in phases (1.45 = phase 2 at 45%). `value={null}` is
 * indeterminate and shimmers unless the user prefers reduced motion.
 */
export interface ProgressProps extends ProgressContract, Omit<HTMLAttributes<HTMLDivElement>, keyof ProgressContract | 'children'> {
  /** Skyline: upstream ProgressContract has no tone. */
  tone?: ContractTone
  /** Draw as this many blocks (phases). `max` defaults to it. */
  segments?: number
  /** e.g. "phase 2 of 3"; becomes aria-valuetext. */
  valueText?: string
}
