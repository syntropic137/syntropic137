import { describe, expect, it } from 'vitest';
import { describeElement } from './describeElement';

function el(html: string): Element {
  const host = document.createElement('div');
  host.innerHTML = html;
  return host.firstElementChild!;
}

describe('describeElement', () => {
  it('prefers the accessible name over the visible text', () => {
    expect(describeElement(el('<button aria-label="Close dialog"><svg></svg>x</button>'))).toBe('button "Close dialog"');
  });

  it('falls back to whitespace-collapsed text content', () => {
    expect(describeElement(el('<a href="/e">\n  Executions\n  <span>12</span></a>'))).toBe('a "Executions 12"');
  });

  it('truncates long text', () => {
    const label = describeElement(el(`<p>${'word '.repeat(30)}</p>`));
    expect(label.startsWith('p "word word')).toBe(true);
    expect(label.endsWith('…"')).toBe(true);
    expect(label.length).toBeLessThanOrEqual('p ""'.length + 40);
  });

  it('is just the tag when the element has no name', () => {
    expect(describeElement(el('<div></div>'))).toBe('div');
  });
});
