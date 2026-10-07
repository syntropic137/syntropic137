import { describe, expect, it } from 'vitest';
import { describeElement } from '../src/utils/describeElement';

function el(html: string): Element {
  const host = document.createElement('div');
  host.innerHTML = html;
  return host.firstElementChild!;
}

describe('describeElement', () => {
  it('labels an element by tag and its collapsed text', () => {
    expect(describeElement(el('<button>\n  Cancel   run\n</button>'))).toBe('button "Cancel run"');
  });

  it('prefers aria-label over text content', () => {
    expect(describeElement(el('<a aria-label="Open execution 42"><svg></svg>42</a>'))).toBe('a "Open execution 42"');
  });

  it('truncates long text', () => {
    const label = describeElement(el(`<p>${'x'.repeat(100)}</p>`));
    expect(label).toBe(`p "${'x'.repeat(39)}…"`);
  });

  it('falls back to the bare tag when there is no text', () => {
    expect(describeElement(el('<div></div>'))).toBe('div');
  });

  it('appends the component name when known', () => {
    expect(describeElement(el('<span>running</span>'), 'ExecutionRow')).toBe('span "running" · <ExecutionRow>');
  });

  it('names the owner of an icon instead of its inner svg path', () => {
    const button = el('<button aria-label="Open navigation"><svg><path d="M0 0"></path></svg></button>');
    expect(describeElement(button.querySelector('path')!, 'Menu')).toBe('icon in button "Open navigation" · <Menu>');
    expect(describeElement(button.querySelector('svg')!)).toBe('icon in button "Open navigation"');
  });
});
