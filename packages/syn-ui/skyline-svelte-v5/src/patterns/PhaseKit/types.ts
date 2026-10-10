import type { PhaseKitProps as PhaseKitData } from '@syn137/skyline-core/patterns'
import type { HTMLAttributes } from 'svelte/elements'

export interface PhaseKitProps extends PhaseKitData, Omit<HTMLAttributes<HTMLElement>, 'title' | 'children'> {
  /** Draw as a card (default) or bare rows inside another card. */
  card?: boolean
}

export interface PhaseKitChipsProps extends Omit<HTMLAttributes<HTMLElement>, 'children'> {
  model?: string | null
  tools: PhaseKitData['tools']
  skills: PhaseKitData['skills']
}
