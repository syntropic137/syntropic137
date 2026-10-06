/**
 * Overlay components used during feedback mode (highlight, pin marker, pinned label, mode hint).
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

export function PinMarker({ locationContext }: { locationContext: LocationContext }) {
  const rect = locationContext.elementRect;
  return (
    <>
      {rect && (
        <div
          className="ui-feedback-pinned-highlight"
          style={{ left: rect.left, top: rect.top, width: rect.width, height: rect.height }}
        />
      )}
      <div className="ui-feedback-pin" style={{ left: locationContext.clickX, top: locationContext.clickY }}>
        <PinIcon />
      </div>
    </>
  );
}

/** Says what the feedback is pinned to, with a way to pick again. */
export function PinnedElementLabel({ locationContext, onRepick }: {
  locationContext: LocationContext; onRepick: () => void;
}) {
  if (!locationContext.elementLabel) return null;
  return (
    <div className="ui-feedback-pinned-label">
      <PinIcon />
      <span className="ui-feedback-pinned-label-text">
        Pinned to <code>{locationContext.elementLabel}</code>
        {locationContext.componentName && <> in <code>&lt;{locationContext.componentName}&gt;</code></>}
      </span>
      <button type="button" className="ui-feedback-pinned-label-repick" onClick={onRepick}>Re-pick</button>
    </div>
  );
}
