/**
 * Hook that registers page click/touch handlers when feedback mode is active.
 * Captures element info on click or tap and opens the modal.
 */

import { useEffect } from 'react';
import type { LocationContext } from '../types';

interface UseFeedbackModeClickOptions {
  isFeedbackMode: boolean;
  captureFromEvent: (e: MouseEvent) => LocationContext;
  captureFromElement: (el: Element, x?: number, y?: number) => LocationContext;
  openModal: (context: LocationContext) => void;
  openQuickFeedback: () => void;
}

/** A touch that travels further than this (px) was a scroll, not a tap. */
const TAP_SLOP = 10;

function getClientCoords(e: MouseEvent | TouchEvent): { clientX?: number; clientY?: number } {
  // On touchend the lifted finger is only in changedTouches; touches is empty.
  if ('changedTouches' in e) {
    return { clientX: e.changedTouches[0]?.clientX, clientY: e.changedTouches[0]?.clientY };
  }
  return { clientX: e.clientX, clientY: e.clientY };
}

function getTarget(e: MouseEvent | TouchEvent): HTMLElement | null {
  return e.target as HTMLElement | null;
}

function captureLocation(
  e: MouseEvent | TouchEvent,
  target: HTMLElement,
  clientX: number,
  clientY: number,
  captureFromEvent: (e: MouseEvent) => LocationContext,
  captureFromElement: (el: Element, x?: number, y?: number) => LocationContext,
): LocationContext {
  if (e instanceof MouseEvent) return captureFromEvent(e);
  return captureFromElement(target, clientX, clientY);
}

function handlePageClick(
  e: MouseEvent | TouchEvent,
  captureFromEvent: (e: MouseEvent) => LocationContext,
  captureFromElement: (el: Element, x?: number, y?: number) => LocationContext,
  openModal: (context: LocationContext) => void,
  openQuickFeedback: () => void,
): void {
  const target = getTarget(e);
  if (target?.closest?.('.ui-feedback-root')) return;

  e.preventDefault();
  e.stopPropagation();

  if (target?.classList?.contains('ui-feedback-mode-overlay')) {
    openQuickFeedback();
    return;
  }

  const { clientX, clientY } = getClientCoords(e);
  if (clientX !== undefined && clientY !== undefined && target) {
    openModal(captureLocation(e, target, clientX, clientY, captureFromEvent, captureFromElement));
  } else {
    openQuickFeedback();
  }
}

export function useFeedbackModeClick({
  isFeedbackMode,
  captureFromEvent,
  captureFromElement,
  openModal,
  openQuickFeedback,
}: UseFeedbackModeClickOptions): void {
  useEffect(() => {
    if (!isFeedbackMode) return;

    const handler = (e: MouseEvent | TouchEvent) =>
      handlePageClick(e, captureFromEvent, captureFromElement, openModal, openQuickFeedback);

    // Pin on touchend rather than waiting for the synthesized click, and
    // cancel it there, so the tap never activates the link or button under
    // the finger. A touch that moved is a scroll and pins nothing.
    let touchStart: { x: number; y: number } | null = null;
    const onTouchStart = (e: TouchEvent) => {
      const t = e.touches[0];
      touchStart = t ? { x: t.clientX, y: t.clientY } : null;
    };
    const onTouchEnd = (e: TouchEvent) => {
      const t = e.changedTouches[0];
      const moved = touchStart && t && Math.hypot(t.clientX - touchStart.x, t.clientY - touchStart.y) > TAP_SLOP;
      touchStart = null;
      if (!moved) handler(e);
    };

    document.addEventListener('click', handler, true);
    document.addEventListener('touchstart', onTouchStart, { capture: true, passive: true });
    document.addEventListener('touchend', onTouchEnd, { capture: true, passive: false });
    document.body.classList.add('ui-feedback-mode-active');

    return () => {
      document.removeEventListener('click', handler, true);
      document.removeEventListener('touchstart', onTouchStart, true);
      document.removeEventListener('touchend', onTouchEnd, true);
      document.body.classList.remove('ui-feedback-mode-active');
    };
  }, [isFeedbackMode, captureFromEvent, captureFromElement, openModal, openQuickFeedback]);
}
