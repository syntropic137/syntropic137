/**
 * Main feedback widget component
 *
 * Renders a floating button and handles the feedback flow:
 * 1. Click button -> Enter feedback mode (or view tickets)
 * 2. Click on page -> Capture location context
 * 3. Open modal -> Fill in feedback
 * 4. Submit -> Send to API
 */

import { useCallback, useEffect, useState } from 'react';
import { FeedbackList } from './components/FeedbackList';
import { FeedbackModal } from './components/FeedbackModal';
import { ElementHighlight, FeedbackModeOverlay, PinMarker } from './components/FeedbackOverlays';
import type { HoverHighlight } from './hooks/useHoverHighlight';
import type { LocationContext } from './types';
import { WidgetButton } from './components/WidgetButton';
import { useFeedback } from './FeedbackContext';
import { useClickOutside } from './hooks/useClickOutside';
import { useDragPosition } from './hooks/useDragPosition';
import { useElementInfo } from './hooks/useElementInfo';
import { useFeedbackApi } from './hooks/useFeedbackApi';
import { useFeedbackModeClick } from './hooks/useFeedbackModeClick';
import { useHoverHighlight } from './hooks/useHoverHighlight';

function handleMenuShortcut(
  e: KeyboardEvent,
  setShowMenu: (v: boolean) => void,
  openQuickFeedback: () => void,
  setShowTickets: (v: boolean) => void,
): void {
  if (!e.ctrlKey || !e.shiftKey) return;
  const key = e.key.toUpperCase();
  if (key === 'Q') { e.preventDefault(); setShowMenu(false); openQuickFeedback(); }
  if (key === 'T') { e.preventDefault(); setShowMenu(false); setShowTickets(true); }
}

export function FeedbackWidget() {
  const {
    isFeedbackMode, isOpen, config,
    openFeedbackMode, closeFeedbackMode, openModal, locationContext,
  } = useFeedback();

  const { captureFromEvent } = useElementInfo();
  const api = useFeedbackApi({ apiUrl: config.apiUrl });
  const { position, isDragging, handleMouseDown, buttonRef } = useDragPosition();
  const hoverHighlight = useHoverHighlight(isFeedbackMode);

  const [showMenu, setShowMenu] = useState(false);
  const [showTickets, setShowTickets] = useState(false);
  const [openCount, setOpenCount] = useState(0);

  useEffect(() => {
    api.getStats(config.appName).then((stats) => {
      setOpenCount(stats.by_status.open || 0);
    }).catch(() => {});
  }, [api, config.appName, isOpen, showTickets]);

  const openQuickFeedback = useCallback(() => {
    openModal({
      url: window.location.href,
      route: window.location.pathname,
      viewportWidth: window.innerWidth,
      viewportHeight: window.innerHeight,
    });
  }, [openModal]);

  useFeedbackModeClick({ isFeedbackMode, captureFromEvent, openModal, openQuickFeedback });
  useClickOutside(buttonRef, () => setShowMenu(false), showMenu);

  useEffect(() => {
    if (config.disabled) return;
    const handler = (e: KeyboardEvent) => handleMenuShortcut(e, setShowMenu, openQuickFeedback, setShowTickets);
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [config.disabled, openQuickFeedback]);

  if (config.disabled) return null;

  const buttonStyle: React.CSSProperties = position
    ? { left: position.x, top: position.y, right: 'auto', bottom: 'auto', transform: 'none' }
    : {};
  const positionClass = position ? '' : `ui-feedback-button--${config.position || 'bottom-right'}`;

  return (
    <div className="ui-feedback-root">
      {!isOpen && !showTickets && (
        <div
          ref={buttonRef}
          className={`ui-feedback-button ${positionClass} ${isDragging ? 'ui-feedback-button--dragging' : ''} ${config.classNames?.button || ''}`}
          style={buttonStyle}
          onMouseDown={handleMouseDown}
        >
          <WidgetButton
            isFeedbackMode={isFeedbackMode}
            isDragging={isDragging}
            showMenu={showMenu}
            openCount={openCount}
            onToggleMenu={() => setShowMenu(!showMenu)}
            onCloseFeedbackMode={closeFeedbackMode}
            onQuickNote={() => { setShowMenu(false); openQuickFeedback(); }}
            onPinToElement={() => { setShowMenu(false); openFeedbackMode(); }}
            onViewTickets={() => { setShowMenu(false); setShowTickets(true); }}
            keyboardShortcut={config.keyboardShortcut}
          />
        </div>
      )}

      <OverlayElements isFeedbackMode={isFeedbackMode} hoverHighlight={hoverHighlight} locationContext={locationContext} isOpen={isOpen} />

      <FeedbackModal />

      {showTickets && (
        <FeedbackList apiUrl={config.apiUrl} appName={config.appName} onClose={() => setShowTickets(false)} />
      )}
    </div>
  );
}

function OverlayElements({ isFeedbackMode, hoverHighlight, locationContext, isOpen }: {
  isFeedbackMode: boolean; hoverHighlight: HoverHighlight | null; locationContext: LocationContext | null; isOpen: boolean;
}) {
  return (
    <>
      {isFeedbackMode && <FeedbackModeOverlay />}
      {isFeedbackMode && hoverHighlight && <ElementHighlight highlight={hoverHighlight} />}
      {locationContext && isOpen && <PinMarker locationContext={locationContext} />}
    </>
  );
}
