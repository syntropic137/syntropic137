import { describe, expect, it } from 'vitest'
import { TASK_TITLE_MAX, inlineSpans, parsePrompt, splitTask } from './index'

describe('parsePrompt (feedback 525d15c0)', () => {
  it('keeps the workflow template shapes', () => {
    expect(parsePrompt('You are a researcher.\n\n## Your Task\n$ARGUMENTS\n\n## How\n- one\n- two\nDone.')).toEqual([
      { kind: 'paragraph', text: 'You are a researcher.' },
      { kind: 'heading', text: 'Your Task' },
      { kind: 'argument', name: '$ARGUMENTS' },
      { kind: 'heading', text: 'How' },
      { kind: 'list', ordered: false, items: [{ text: 'one', items: [] }, { text: 'two', items: [] }] },
      { kind: 'paragraph', text: 'Done.' },
    ])
    expect(parsePrompt('{{ task }}')).toEqual([{ kind: 'argument', name: 'task' }])
    expect(parsePrompt(null)).toEqual([])
  })

  it('parses an ordered list with nested bullets and continuation lines', () => {
    const b = parsePrompt('Do all four:\n1. First\n   - a `x.py:1`\n   - b\n2. Second\n   wraps here\n\n3. Third\nTRAPS: none')
    expect(b).toEqual([
      { kind: 'paragraph', text: 'Do all four:' },
      {
        kind: 'list',
        ordered: true,
        items: [
          { text: 'First', items: ['a `x.py:1`', 'b'] },
          { text: 'Second wraps here', items: [] },
          { text: 'Third', items: [] },
        ],
      },
      { kind: 'paragraph', text: 'TRAPS: none' },
    ])
  })

  it('splits a list when the marker kind changes', () => {
    const b = parsePrompt('- a\n1. b')
    expect(b.map((x) => x.kind === 'list' && x.ordered)).toEqual([false, true])
  })

  it('keeps fenced code verbatim, markers and all', () => {
    expect(parsePrompt('Run:\n```sh\n# not a heading\n- not a list\n```\nok')).toEqual([
      { kind: 'paragraph', text: 'Run:' },
      { kind: 'code', text: '# not a heading\n- not a list' },
      { kind: 'paragraph', text: 'ok' },
    ])
    expect(parsePrompt('```\nopen')).toEqual([{ kind: 'code', text: 'open' }])
  })
})

describe('inlineSpans', () => {
  it('splits code and strong runs', () => {
    expect(inlineSpans('see `a.py` and **KEPT** now')).toEqual([
      { kind: 'text', text: 'see ' },
      { kind: 'code', text: 'a.py' },
      { kind: 'text', text: ' and ' },
      { kind: 'strong', text: 'KEPT' },
      { kind: 'text', text: ' now' },
    ])
  })
  it('leaves unclosed markers literal', () => {
    expect(inlineSpans('a `b')).toEqual([{ kind: 'text', text: 'a `b' }])
    expect(inlineSpans('')).toEqual([])
  })
})

describe('splitTask', () => {
  it('uses a short first line as the title and the rest as body', () => {
    expect(splitTask('# Fix the thing\n\n1. one\n2. two')).toEqual({ title: 'Fix the thing', body: '1. one\n2. two' })
    expect(splitTask('Just do it')).toEqual({ title: 'Just do it', body: '' })
    expect(splitTask(null)).toEqual({ title: '', body: '' })
  })
  it('clips a long first line at a word and keeps the whole task in the body', () => {
    const first = 'Fix #1771 (follow-ups from the independent verification of the merged workspace dir reclaim, PR #1755). Body:'
    const task = `${first} ${first}\nmore`
    const p = splitTask(task)
    expect(p.title.length).toBeLessThanOrEqual(TASK_TITLE_MAX + 1)
    expect(p.title.endsWith('…')).toBe(true)
    expect(p.title.startsWith('Fix #1771')).toBe(true)
    expect(p.body).toBe(task)
  })
})
