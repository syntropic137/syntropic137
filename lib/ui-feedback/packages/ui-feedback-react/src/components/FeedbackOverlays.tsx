/**
 * Overlay components used during feedback mode (highlight, pin marker, mode hint).
 */

import type { HoverHighlight } from '../hooks/useHoverHighlight';
import type { LocationContext } from '../types';
import { PinIcon } from './icons';

export function FeedbackModeOverlay() {
  return (
    <div className="ui-feedback-mode-overlay">
      <div className="ui-feedback-mode-hint">
        {'\u{1F3AF}'} Click or tap any element to pin feedback {'\u2022'} <kbd>Esc</kbd> to cancel
      </div>
    </div>
  );
}

export function ElementHighlight({ highlight }: { highlight: HoverHighlight }) {
  return (
    <div
      className="ui-feedback-element-highlight"
      data-component={highlight.componentName || 'element'}
      style={{
        left: highlight.rect.left, top: highlight.rect.top,
        width: highlight.rect.width, height: highlight.rect.height,
      }}
    />
  );
}

function findPinnedElement(selector: string | undefined): Element | null {
  if (!selector) return null;
  try {
    return document.querySelector(selector);
  } catch {
    return null;
  }
}

/** Outlines the pinned element, labels it, and marks the exact click/tap point. */
export function PinMarker({ locationContext }: { locationContext: LocationContext }) {
  const rect = findPinnedElement(locationContext.cssSelector)?.getBoundingClientRect();
  return (
    <>
      {rect && (
        <div
          className="ui-feedback-pinned-highlight"
          data-label={locationContext.elementLabel}
          style={{ left: rect.left, top: rect.top, width: rect.width, height: rect.height }}
        />
      )}
      <div className="ui-feedback-pin" style={{ left: locationContext.clickX, top: locationContext.clickY }}>
        <PinIcon />
      </div>
    </>
  );
}
