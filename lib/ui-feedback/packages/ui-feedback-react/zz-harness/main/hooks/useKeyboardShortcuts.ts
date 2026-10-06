/**
 * Hook for keyboard shortcut handling in the feedback widget.
 */

import { useEffect } from 'react';
import { parseShortcut } from '../utils/parseShortcut';

interface KeyboardShortcutsOptions {
  disabled: boolean;
  keyboardShortcut: string;
  isFeedbackMode: boolean;
  isOpen: boolean;
  openFeedbackMode: () => void;
  closeFeedbackMode: () => void;
  closeModal: () => void;
}

interface Actions {
  openFeedbackMode: () => void;
  closeFeedbackMode: () => void;
  closeModal: () => void;
}

function toggleFeedbackMode(isFeedbackMode: boolean, isOpen: boolean, actions: Actions): void {
  if (isFeedbackMode) { actions.closeFeedbackMode(); return; }
  if (isOpen) { actions.closeModal(); return; }
  actions.openFeedbackMode();
}

function handleEscape(isFeedbackMode: boolean, isOpen: boolean, actions: Actions): void {
  if (isFeedbackMode) actions.closeFeedbackMode();
  else if (isOpen) actions.closeModal();
}

function handleShortcutKey(
  e: KeyboardEvent,
  matcher: (e: KeyboardEvent) => boolean,
  isFeedbackMode: boolean,
  isOpen: boolean,
  actions: Actions,
): void {
  if (matcher(e)) {
    e.preventDefault();
    toggleFeedbackMode(isFeedbackMode, isOpen, actions);
  }
  if (e.key === 'Escape') {
    handleEscape(isFeedbackMode, isOpen, actions);
  }
}

export function useKeyboardShortcuts({
  disabled, keyboardShortcut, isFeedbackMode, isOpen,
  openFeedbackMode, closeFeedbackMode, closeModal,
}: KeyboardShortcutsOptions): void {
  useEffect(() => {
    if (disabled) return;
    const matcher = parseShortcut(keyboardShortcut);
    const actions = { openFeedbackMode, closeFeedbackMode, closeModal };
    const handler = (e: KeyboardEvent) => handleShortcutKey(e, matcher, isFeedbackMode, isOpen, actions);
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [disabled, keyboardShortcut, isFeedbackMode, isOpen, openFeedbackMode, closeFeedbackMode, closeModal]);
}
