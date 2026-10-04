/**
 * Hook for a single-key shortcut on a form control (e.g. "1" opens the type picker).
 *
 * A bare key is only a shortcut while the user is not typing: the same "1" in
 * the comment box must type a 1. So the key is ignored whenever focus is in a
 * text-entry element or a modifier is held (those belong to the browser and to
 * the widget's own Ctrl+Shift shortcuts). The listener lives exactly as long
 * as the component using it, which is what scopes it to the open form.
 */

import { useEffect, useRef } from 'react';

function isTextEntry(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  return target.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName);
}

function isBareKey(e: KeyboardEvent, key: string): boolean {
  return e.key === key && !e.ctrlKey && !e.metaKey && !e.altKey;
}

export function useFormHotkey(key: string | undefined, onPress: () => void): void {
  const onPressRef = useRef(onPress);
  onPressRef.current = onPress;

  useEffect(() => {
    if (!key) return;
    const handler = (e: KeyboardEvent) => {
      if (!isBareKey(e, key) || isTextEntry(e.target)) return;
      e.preventDefault();
      onPressRef.current();
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [key]);
}
