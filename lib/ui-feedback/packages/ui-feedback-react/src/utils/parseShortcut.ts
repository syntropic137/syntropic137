/**
 * Parse a keyboard shortcut string (e.g., "Ctrl+Shift+F") into a matcher function.
 */
export function parseShortcut(shortcut: string): (e: KeyboardEvent) => boolean {
  const parts = shortcut.split('+').map((p) => p.toLowerCase().trim());
  const key = parts.pop();

  const modifiers = {
    ctrl: parts.includes('ctrl'),
    shift: parts.includes('shift'),
    alt: parts.includes('alt'),
    meta: parts.includes('meta') || parts.includes('cmd'),
  };

  return (e: KeyboardEvent) =>
    e.key.toLowerCase() === key &&
    e.ctrlKey === modifiers.ctrl &&
    e.shiftKey === modifiers.shift &&
    e.altKey === modifiers.alt &&
    e.metaKey === modifiers.meta;
}
