/**
 * Hook that registers page click/touch handlers when feedback mode is active.
 * Captures element info on click and opens the modal.
 */

import { useEffect } from 'react';
import type { LocationContext } from '../types';

interface UseFeedbackModeClickOptions {
  isFeedbackMode: boolean;
  captureFromEvent: (e: MouseEvent) => LocationContext;
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

export function useFeedbackModeClick({
  isFeedbackMode,
  captureFromEvent,
  openModal,
  openQuickFeedback,
}: UseFeedbackModeClickOptions): void {
  useEffect(() => {
    if (!isFeedbackMode) return;

    const handlePageClick = (e: MouseEvent | TouchEvent) => {
      const target = getTarget(e);
      if (target?.closest?.('.ui-feedback-root')) return;

      e.preventDefault();
      e.stopPropagation();

      if (target?.classList?.contains('ui-feedback-mode-overlay')) {
        openQuickFeedback();
        return;
      }

      const { clientX, clientY } = getClientCoords(e);
      if (clientX !== undefined && clientY !== undefined) {
        openModal(captureFromEvent(e as MouseEvent));
      } else {
        openQuickFeedback();
      }
    };

    document.addEventListener('click', handlePageClick, true);
    document.addEventListener('touchend', handlePageClick as EventListener, true);
    document.body.classList.add('ui-feedback-mode-active');

    return () => {
      document.removeEventListener('click', handlePageClick, true);
      document.removeEventListener('touchend', handlePageClick as EventListener, true);
      document.body.classList.remove('ui-feedback-mode-active');
    };
  }, [isFeedbackMode, captureFromEvent, openModal, openQuickFeedback]);
}
