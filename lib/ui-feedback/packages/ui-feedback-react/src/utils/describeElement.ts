/**
 * Human-readable label for a pinned element, e.g. `button "Cancel run" · <ExecutionRow>`.
 *
 * Shown to the person leaving feedback so they can see WHAT they pinned
 * before submitting. It is display-only: the stored location keeps the
 * css selector / xpath, which are what a developer resolves later.
 */

const MAX_TEXT = 40;

function accessibleText(el: Element): string {
  const aria = el.getAttribute('aria-label') || el.getAttribute('title') || el.getAttribute('alt');
  if (aria) return aria;
  if (el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement) {
    return el.placeholder || el.name || '';
  }
  return el.textContent ?? '';
}

function truncate(text: string): string {
  const collapsed = text.replace(/\s+/g, ' ').trim();
  return collapsed.length > MAX_TEXT ? `${collapsed.slice(0, MAX_TEXT - 1)}…` : collapsed;
}

function describeOne(el: Element): string {
  const tag = el.tagName.toLowerCase();
  const text = truncate(accessibleText(el));
  return text ? `${tag} "${text}"` : tag;
}

export function describeElement(el: Element, componentName?: string | null): string {
  // A tap on an icon lands on an inner <path>/<svg>, whose tag says nothing;
  // name the HTML element that owns the icon instead (e.g. its button).
  const iconOwner = el instanceof SVGElement ? el.closest('svg')?.parentElement : null;
  const base = iconOwner ? `icon in ${describeOne(iconOwner)}` : describeOne(el);
  return componentName ? `${base} · <${componentName}>` : base;
}
