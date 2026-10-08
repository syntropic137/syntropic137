import { describe, expect, it } from 'vitest'
import {
  clampPage,
  commandScore,
  filterCommandGroups,
  listMoveForKey,
  moveIndex,
  paginationRange,
  selectAllState,
  shownCount,
  toggleValue,
  typeaheadIndex,
} from './index'

describe('listMoveForKey', () => {
  it('maps arrows by orientation', () => {
    expect(listMoveForKey('ArrowRight', 'horizontal')).toBe('next')
    expect(listMoveForKey('ArrowDown', 'horizontal')).toBeNull()
    expect(listMoveForKey('ArrowDown', 'vertical')).toBe('next')
    expect(listMoveForKey('ArrowLeft', 'vertical')).toBeNull()
    expect(listMoveForKey('ArrowUp', 'both')).toBe('prev')
    expect(listMoveForKey('Home')).toBe('first')
    expect(listMoveForKey('End')).toBe('last')
    expect(listMoveForKey('a')).toBeNull()
  })
  it('flips horizontal arrows in rtl', () => {
    expect(listMoveForKey('ArrowRight', 'horizontal', 'rtl')).toBe('prev')
  })
})

describe('moveIndex', () => {
  const d = [false, true, false, false]
  it('skips disabled items and wraps', () => {
    expect(moveIndex(0, 'next', d)).toBe(2)
    expect(moveIndex(3, 'next', d)).toBe(0)
    expect(moveIndex(0, 'prev', d)).toBe(3)
    expect(moveIndex(2, 'prev', d)).toBe(0)
  })
  it('finds first and last enabled', () => {
    expect(moveIndex(2, 'first', [true, false, false])).toBe(1)
    expect(moveIndex(0, 'last', [false, false, true])).toBe(1)
  })
  it('stays put at the ends without loop', () => {
    expect(moveIndex(3, 'next', d, false)).toBe(3)
    expect(moveIndex(0, 'prev', d, false)).toBe(0)
  })
  it('starts from nothing focused', () => {
    expect(moveIndex(-1, 'next', d)).toBe(0)
    expect(moveIndex(-1, 'prev', d)).toBe(3)
  })
  it('returns -1 when nothing is enabled', () => {
    expect(moveIndex(0, 'next', [true, true])).toBe(-1)
    expect(moveIndex(0, 'next', [])).toBe(-1)
  })
})

describe('typeaheadIndex', () => {
  const labels = ['Evals', 'Triggers', 'Sessions', 'Settings', 'Repos']
  const none = labels.map(() => false)
  it('finds the next item starting with the query', () => {
    expect(typeaheadIndex(labels, none, 0, 's')).toBe(2)
    expect(typeaheadIndex(labels, none, 2, 's')).toBe(3)
    expect(typeaheadIndex(labels, none, 3, 's')).toBe(2)
  })
  it('matches multi-letter queries including the current item', () => {
    expect(typeaheadIndex(labels, none, 3, 'set')).toBe(3)
    expect(typeaheadIndex(labels, none, 0, 'ses')).toBe(2)
  })
  it('cycles on a repeated letter and skips disabled', () => {
    expect(typeaheadIndex(labels, none, 2, 'ss')).toBe(3)
    expect(typeaheadIndex(labels, [false, false, true, false, false], 0, 's')).toBe(3)
  })
  it('returns -1 for no match', () => {
    expect(typeaheadIndex(labels, none, 0, 'z')).toBe(-1)
    expect(typeaheadIndex(labels, none, 0, '')).toBe(-1)
  })
})

describe('toggleValue', () => {
  it('single keeps at most one', () => {
    expect(toggleValue([], 'a', 'single')).toEqual(['a'])
    expect(toggleValue(['a'], 'b', 'single')).toEqual(['b'])
    expect(toggleValue(['a'], 'a', 'single')).toEqual([])
  })
  it('single without allowEmpty behaves like a segmented control', () => {
    expect(toggleValue(['a'], 'a', 'single', false)).toEqual(['a'])
  })
  it('multiple adds and removes', () => {
    expect(toggleValue(['a'], 'b', 'multiple')).toEqual(['a', 'b'])
    expect(toggleValue(['a', 'b'], 'a', 'multiple')).toEqual(['b'])
  })
})

describe('selectAllState', () => {
  it('is false, indeterminate or true', () => {
    expect(selectAllState([], ['a', 'b'])).toBe(false)
    expect(selectAllState(['a'], ['a', 'b'])).toBe('indeterminate')
    expect(selectAllState(['b', 'a', 'z'], ['a', 'b'])).toBe(true)
    expect(selectAllState(['a'], [])).toBe(false)
  })
})

describe('pagination', () => {
  it('clamps pages', () => {
    expect(clampPage(0, 3)).toBe(1)
    expect(clampPage(9, 3)).toBe(3)
    expect(clampPage(Number.NaN, 3)).toBe(1)
    expect(clampPage(2, 0)).toBe(1)
  })
  it('lists every page when they fit', () => {
    expect(paginationRange(1, 3)).toEqual([1, 2, 3])
    expect(paginationRange(4, 7)).toEqual([1, 2, 3, 4, 5, 6, 7])
  })
  it('adds gaps and keeps a constant length', () => {
    expect(paginationRange(1, 20)).toEqual([1, 2, 3, 4, 5, 'gap', 20])
    expect(paginationRange(10, 20)).toEqual([1, 'gap', 9, 10, 11, 'gap', 20])
    expect(paginationRange(20, 20)).toEqual([1, 'gap', 16, 17, 18, 19, 20])
    expect(paginationRange(10, 20, 2)).toHaveLength(9)
  })
  it('counts items shown so far', () => {
    expect(shownCount(1, 12, 27)).toBe(12)
    expect(shownCount(3, 12, 27)).toBe(27)
    expect(shownCount(1, 12, 0)).toBe(0)
  })
})

describe('command filter', () => {
  const wf = { label: 'Research Workflow', keywords: ['research-workflow-v2'] }
  it('ranks exact, prefix, word, substring, keyword, subsequence', () => {
    expect(commandScore('research workflow', wf)).toBe(1000)
    expect(commandScore('resea', wf)).toBe(800)
    expect(commandScore('work', wf)).toBe(600)
    expect(commandScore('orkfl', wf)).toBe(400)
    expect(commandScore('v2', wf)).toBe(300)
    expect(commandScore('rsw', wf)).toBeGreaterThan(0)
    expect(commandScore('zz', wf)).toBe(0)
    expect(commandScore('', wf)).toBe(1)
  })
  it('filters groups, sorts by score and drops empty groups', () => {
    const groups = [
      { heading: 'Workflows', items: [{ label: 'Research with Prompt Files' }, wf] },
      { heading: 'Go to', items: [{ label: 'Evals' }] },
    ]
    const out = filterCommandGroups(groups, 'research wo')
    expect(out).toHaveLength(1)
    expect(out[0]!.items.map((i) => i.label)).toEqual(['Research Workflow', 'Research with Prompt Files'])
    expect(filterCommandGroups(groups, '')).toHaveLength(2)
  })
})
