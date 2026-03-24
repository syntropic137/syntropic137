/**
 * Hook that registers page click/touch handlers when feedback mode is active.
 * Captures element info on click and opens the modal.
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

function getClientCoords(e: MouseEvent | TouchEvent): { clientX?: number; clientY?: number } {
  if ('touches' in e) {
    return { clientX: e.touches[0]?.clientX, clientY: e.touches[0]?.clientY };
  }
  return { clientX: e.clientX, clientY: e.clientY };
}

function getTarget(e: MouseEvent | TouchEvent): HTMLElement | null {
  return (e.target || (e as TouchEvent).touches?.[0]?.target) as HTMLElement | null;
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

    document.addEventListener('click', handler, true);
    document.addEventListener('touchend', handler as EventListener, true);
    document.body.classList.add('ui-feedback-mode-active');

    return () => {
      document.removeEventListener('click', handler, true);
      document.removeEventListener('touchend', handler as EventListener, true);
      document.body.classList.remove('ui-feedback-mode-active');
    };
  }, [isFeedbackMode, captureFromEvent, captureFromElement, openModal, openQuickFeedback]);
}
