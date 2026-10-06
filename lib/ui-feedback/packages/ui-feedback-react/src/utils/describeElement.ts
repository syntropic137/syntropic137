/**
 * A short human label for a DOM element, shown back to the user after they
 * pin feedback to it ("button "Cancel"", "a "Executions"", "td "running"").
 *
 * The accessible name wins over visible text because it is what the element
 * is *called*; an icon button has no text but usually has an aria-label.
 */

const MAX_NAME_LENGTH = 40;

function accessibleName(el: Element): string | null {
  for (const attr of ['aria-label', 'title', 'alt', 'placeholder']) {
    const value = el.getAttribute(attr)?.trim();
    if (value) return value;
  }
  const text = el.textContent?.replace(/\s+/g, ' ').trim();
  return text || null;
}

function truncate(value: string): string {
  return value.length > MAX_NAME_LENGTH ? `${value.slice(0, MAX_NAME_LENGTH - 1)}…` : value;
}

export function describeElement(el: Element): string {
  const tag = el.tagName.toLowerCase();
  const name = accessibleName(el);
  return name ? `${tag} "${truncate(name)}"` : tag;
}
