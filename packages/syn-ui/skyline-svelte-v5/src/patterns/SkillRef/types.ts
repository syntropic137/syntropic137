import type { SkillRefProps as SkillRefData } from '@syn137/skyline-core/patterns'
import type { HTMLAttributes } from 'svelte/elements'

export interface SkillRefProps extends SkillRefData, Omit<HTMLAttributes<HTMLElement>, 'children'> {
  /** `full`: name, source @ ref with a source link, and the pinned content digest. `chip`: the compact chip on cards. */
  variant?: 'full' | 'chip'
}
