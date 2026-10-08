/**
 * Hook that registers page click/tap handlers when feedback mode is active.
 * Captures element info on click or tap and opens the modal.
 *
 * Touch is handled on `touchend`, not on the synthetic `click` that follows:
 * cancelling the `touchend` is what stops the tap from also following the
 * link or pressing the button underneath. A touch that moved further than
 * TAP_SLOP_PX is a scroll, not a pick, and is left alone.
 */

import { useEffect } from 'react';
import type { LocationContext } from '../types';

export const TAP_SLOP_PX = 10;

interface UseFeedbackModeClickOptions {
  isFeedbackMode: boolean;
  captureFromElement: (el: Element, x?: number, y?: number) => LocationContext;
  openModal: (context: LocationContext) => void;
  openQuickFeedback: () => void;
}

interface Point { x: number; y: number }

function pin(
  e: Event,
  point: Point,
  captureFromElement: (el: Element, x?: number, y?: number) => LocationContext,
  openModal: (context: LocationContext) => void,
  openQuickFeedback: () => void,
): void {
  const target = e.target instanceof Element ? e.target : null;
  if (target?.closest('.ui-feedback-root')) return;

  e.preventDefault();
  e.stopPropagation();

  if (!target || target.classList.contains('ui-feedback-mode-overlay')) {
    openQuickFeedback();
    return;
  }
  openModal(captureFromElement(target, point.x, point.y));
}

export function useFeedbackModeClick({
  isFeedbackMode,
  captureFromElement,
  openModal,
  openQuickFeedback,
}: UseFeedbackModeClickOptions): void {
  useEffect(() => {
    if (!isFeedbackMode) return;

    let touchStart: Point | null = null;

    const onClick = (e: MouseEvent) =>
      pin(e, { x: e.clientX, y: e.clientY }, captureFromElement, openModal, openQuickFeedback);

    const onTouchStart = (e: TouchEvent) => {
      const t = e.changedTouches[0];
      touchStart = e.touches.length === 1 && t ? { x: t.clientX, y: t.clientY } : null;
    };

    // On touchend the lifted finger is in changedTouches; `touches` is already empty.
    const onTouchEnd = (e: TouchEvent) => {
      const t = e.changedTouches[0];
      const start = touchStart;
      touchStart = null;
      if (!t || !start) return;
      if (Math.hypot(t.clientX - start.x, t.clientY - start.y) > TAP_SLOP_PX) return;
      pin(e, { x: Math.round(t.clientX), y: Math.round(t.clientY) }, captureFromElement, openModal, openQuickFeedback);
    };

    document.addEventListener('click', onClick, true);
    document.addEventListener('touchstart', onTouchStart, { capture: true, passive: true });
    document.addEventListener('touchend', onTouchEnd, { capture: true, passive: false });
    document.body.classList.add('ui-feedback-mode-active');

    return () => {
      document.removeEventListener('click', onClick, true);
      document.removeEventListener('touchstart', onTouchStart, true);
      document.removeEventListener('touchend', onTouchEnd, true);
      document.body.classList.remove('ui-feedback-mode-active');
    };
  }, [isFeedbackMode, captureFromElement, openModal, openQuickFeedback]);
}
