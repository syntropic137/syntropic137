/**
 * Main feedback widget component
 *
 * Renders a floating button and handles the feedback flow:
 * 1. Click button → Enter feedback mode (or view tickets)
 * 2. Click on page → Capture location context
 * 3. Open modal → Fill in feedback
 * 4. Submit → Send to API
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { FeedbackList } from './components/FeedbackList';
import { FeedbackModal } from './components/FeedbackModal';
import { useFeedback } from './FeedbackContext';
import { useElementInfo } from './hooks/useElementInfo';
import { useFeedbackApi } from './hooks/useFeedbackApi';
import { getReactComponentName, getComponentInfo } from './utils/getReactComponent';

export function FeedbackWidget() {
  const {
    isFeedbackMode,
    isOpen,
    config,
    openFeedbackMode,
    closeFeedbackMode,
    openModal,
    locationContext,
  } = useFeedback();

  const { captureFromEvent } = useElementInfo();
  const api = useFeedbackApi({ apiUrl: config.apiUrl });

  // State
  const [showMenu, setShowMenu] = useState(false);
  const [showTickets, setShowTickets] = useState(false);
  const [openCount, setOpenCount] = useState(0);
  const [position, setPosition] = useState<{ x: number; y: number } | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [hoverHighlight, setHoverHighlight] = useState<{
    rect: DOMRect;
    componentName: string | null;
  } | null>(null);
  const dragStartRef = useRef<{ x: number; y: number; buttonX: number; buttonY: number } | null>(null);
  const buttonRef = useRef<HTMLDivElement>(null);

  // Load open ticket count
  useEffect(() => {
    api.getStats(config.appName).then((stats) => {
      setOpenCount(stats.by_status.open || 0);
    }).catch(() => {
      // Ignore errors on initial load
    });
  }, [api, config.appName, isOpen, showTickets]);

  // Load saved position from localStorage
  useEffect(() => {
    const saved = localStorage.getItem('ui-feedback-position');
    if (saved) {
      try {
        setPosition(JSON.parse(saved));
      } catch {
        // Ignore
      }
    }
  }, []);

  // Open quick feedback (just captures URL, no element)
  const openQuickFeedback = useCallback(() => {
    const context = {
      url: window.location.href,
      route: window.location.pathname,
      viewportWidth: window.innerWidth,
      viewportHeight: window.innerHeight,
      // No click coordinates or element info
      clickX: undefined,
      clickY: undefined,
      cssSelector: undefined,
      xpath: undefined,
      componentName: undefined,
    };
    openModal(context);
  }, [openModal]);

  // Handle click in feedback mode
  const handlePageClick = useCallback(
    (e: MouseEvent | TouchEvent) => {
      if (!isFeedbackMode) return;

      const target = (e.target || (e as TouchEvent).touches?.[0]?.target) as HTMLElement;
      if (target?.closest?.('.ui-feedback-root')) return;

      e.preventDefault();
      e.stopPropagation();

      // Check if clicking on the overlay itself (not on content) - open quick feedback
      if (target?.classList?.contains('ui-feedback-mode-overlay')) {
        openQuickFeedback();
        return;
      }

      // Get coordinates from either mouse or touch event
      const clientX = 'touches' in e ? e.touches[0]?.clientX : e.clientX;
      const clientY = 'touches' in e ? e.touches[0]?.clientY : e.clientY;

      if (clientX !== undefined && clientY !== undefined) {
        const context = captureFromEvent(e as MouseEvent);
        openModal(context);
      } else {
        // Fallback to quick feedback if we can't get coordinates
        openQuickFeedback();
      }
    },
    [isFeedbackMode, captureFromEvent, openModal, openQuickFeedback]
  );

  useEffect(() => {
    if (isFeedbackMode) {
      // Add both mouse and touch listeners for mobile support
      document.addEventListener('click', handlePageClick, true);
      document.addEventListener('touchend', handlePageClick as EventListener, true);
      // Add body class for cursor styling
      document.body.classList.add('ui-feedback-mode-active');
      return () => {
        document.removeEventListener('click', handlePageClick, true);
        document.removeEventListener('touchend', handlePageClick as EventListener, true);
        document.body.classList.remove('ui-feedback-mode-active');
      };
    }
  }, [isFeedbackMode, handlePageClick]);

  // Handle hover highlighting in feedback mode
  useEffect(() => {
    if (!isFeedbackMode) {
      setHoverHighlight(null);
      return;
    }

    // Elements to skip when highlighting (too big/generic)
    const skipTags = new Set(['HTML', 'BODY', 'MAIN', 'ARTICLE', 'SECTION', 'ASIDE', 'HEADER', 'FOOTER', 'NAV']);
    const minSize = 20; // Minimum element size in pixels

    const findBestElement = (x: number, y: number): HTMLElement | null => {
      // Get all elements at this point
      const elements = document.elementsFromPoint(x, y) as HTMLElement[];

      for (const el of elements) {
        // Skip our own UI elements
        if (el.closest('.ui-feedback-root')) continue;
        if (el.classList.contains('ui-feedback-mode-overlay')) continue;
        if (el.classList.contains('ui-feedback-mode-hint')) continue;
        if (el.classList.contains('ui-feedback-element-highlight')) continue;

        // Skip very large container elements
        if (skipTags.has(el.tagName)) continue;

        // Get element bounds
        const rect = el.getBoundingClientRect();

        // Skip elements that are too big (more than 80% of viewport)
        const viewportArea = window.innerWidth * window.innerHeight;
        const elementArea = rect.width * rect.height;
        if (elementArea > viewportArea * 0.8) continue;

        // Skip elements that are too small
        if (rect.width < minSize || rect.height < minSize) continue;

        return el;
      }

      return null;
    };

    const handleMouseMove = (e: MouseEvent) => {
      const target = findBestElement(e.clientX, e.clientY);

      if (!target) {
        setHoverHighlight(null);
        return;
      }

      // Get element bounds
      const rect = target.getBoundingClientRect();

      // Try to get React component name
      const componentName = getReactComponentName(target) || getComponentInfo(target);

      setHoverHighlight({
        rect,
        componentName,
      });
    };

    const handleMouseLeave = () => {
      setHoverHighlight(null);
    };

    document.addEventListener('mousemove', handleMouseMove);
    document.addEventListener('mouseleave', handleMouseLeave);

    return () => {
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseleave', handleMouseLeave);
      setHoverHighlight(null);
    };
  }, [isFeedbackMode]);

  // Close menu when clicking outside
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (showMenu && buttonRef.current && !buttonRef.current.contains(e.target as Node)) {
        setShowMenu(false);
      }
    };
    document.addEventListener('click', handleClickOutside);
    return () => document.removeEventListener('click', handleClickOutside);
  }, [showMenu]);

  // Drag handlers
  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    if (e.button !== 0) return;
    const rect = buttonRef.current?.getBoundingClientRect();
    if (!rect) return;

    dragStartRef.current = {
      x: e.clientX,
      y: e.clientY,
      buttonX: rect.left,
      buttonY: rect.top,
    };
  }, []);

  const handleMouseMove = useCallback((e: MouseEvent) => {
    if (!dragStartRef.current) return;

    const dx = Math.abs(e.clientX - dragStartRef.current.x);
    const dy = Math.abs(e.clientY - dragStartRef.current.y);

    // Start dragging after moving 5px
    if (dx > 5 || dy > 5) {
      setIsDragging(true);
      const newX = dragStartRef.current.buttonX + (e.clientX - dragStartRef.current.x);
      const newY = dragStartRef.current.buttonY + (e.clientY - dragStartRef.current.y);

      // Constrain to viewport
      const maxX = window.innerWidth - 60;
      const maxY = window.innerHeight - 60;
      setPosition({
        x: Math.max(12, Math.min(maxX, newX)),
        y: Math.max(12, Math.min(maxY, newY)),
      });
    }
  }, []);

  const handleMouseUp = useCallback(() => {
    if (isDragging && position) {
      localStorage.setItem('ui-feedback-position', JSON.stringify(position));
    }
    dragStartRef.current = null;
    setTimeout(() => setIsDragging(false), 0);
  }, [isDragging, position]);

  useEffect(() => {
    document.addEventListener('mousemove', handleMouseMove);
    document.addEventListener('mouseup', handleMouseUp);
    return () => {
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', handleMouseUp);
    };
  }, [handleMouseMove, handleMouseUp]);

  if (config.disabled) return null;

  // Calculate button style
  const buttonStyle: React.CSSProperties = position
    ? { left: position.x, top: position.y, right: 'auto', bottom: 'auto', transform: 'none' }
    : {};

  const positionClass = position ? '' : `ui-feedback-button--${config.position || 'bottom-right'}`;

  // Keyboard shortcuts for menu items
  useEffect(() => {
    if (config.disabled) return;

    const handleMenuShortcuts = (e: KeyboardEvent) => {
      // Only handle Ctrl+Shift combinations
      if (!e.ctrlKey || !e.shiftKey) return;

      const key = e.key.toUpperCase();

      // Ctrl+Shift+Q = Quick Note
      if (key === 'Q') {
        e.preventDefault();
        setShowMenu(false);
        openQuickFeedback();
        return;
      }

      // Ctrl+Shift+T = View Tickets
      if (key === 'T') {
        e.preventDefault();
        setShowMenu(false);
        setShowTickets(true);
        return;
      }

      // Note: Ctrl+Shift+F (Pin to Element) is already handled in FeedbackProvider
    };

    window.addEventListener('keydown', handleMenuShortcuts);
    return () => window.removeEventListener('keydown', handleMenuShortcuts);
  }, [config.disabled, openQuickFeedback]);

  return (
    // Wrap all widget UI in ui-feedback-root so click handling can identify it
    <div className="ui-feedback-root">
      {/* Floating button with menu */}
      {!isOpen && !showTickets && (
        <div
          ref={buttonRef}
          className={`ui-feedback-button ${positionClass} ${isDragging ? 'ui-feedback-button--dragging' : ''} ${config.classNames?.button || ''}`}
          style={buttonStyle}
          onMouseDown={handleMouseDown}
        >
          {isFeedbackMode ? (
            <button
              type="button"
              className="ui-feedback-button-inner"
              onClick={() => !isDragging && closeFeedbackMode()}
              title="Cancel (Esc)"
            >
              <CloseIcon />
            </button>
          ) : (
            <>
              <button
                type="button"
                className="ui-feedback-button-inner"
                onClick={() => !isDragging && setShowMenu(!showMenu)}
                title={`Feedback (${config.keyboardShortcut})`}
              >
                <FeedbackIcon />
              </button>
              {openCount > 0 && (
                <span className="ui-feedback-button-badge">{openCount}</span>
              )}
            </>
          )}

          {/* Dropdown menu with hotkey hints */}
          {showMenu && !isDragging && (
            <div className="ui-feedback-menu">
              <button
                className="ui-feedback-menu-item"
                onClick={() => {
                  setShowMenu(false);
                  openQuickFeedback();
                }}
              >
                <NoteIcon />
                <span className="ui-feedback-menu-label">Quick Note</span>
                <kbd className="ui-feedback-menu-hotkey">⌃⇧Q</kbd>
              </button>
              <button
                className="ui-feedback-menu-item"
                onClick={() => {
                  setShowMenu(false);
                  openFeedbackMode();
                }}
              >
                <PinSelectIcon />
                <span className="ui-feedback-menu-label">Pin to Element</span>
                <kbd className="ui-feedback-menu-hotkey">⌃⇧F</kbd>
              </button>
              <button
                className="ui-feedback-menu-item"
                onClick={() => {
                  setShowMenu(false);
                  setShowTickets(true);
                }}
              >
                <ListIcon />
                <span className="ui-feedback-menu-label">View Tickets</span>
                {openCount > 0 && <span className="ui-feedback-menu-badge">{openCount}</span>}
                <kbd className="ui-feedback-menu-hotkey">⌃⇧T</kbd>
              </button>
            </div>
          )}
        </div>
      )}

      {/* Feedback mode hint */}
      {isFeedbackMode && (
        <div className="ui-feedback-mode-overlay">
          <div className="ui-feedback-mode-hint">
            🎯 Click on any element to pin feedback • <kbd>Esc</kbd> to cancel
          </div>
        </div>
      )}

      {/* Element highlight on hover */}
      {isFeedbackMode && hoverHighlight && (
        <div
          className="ui-feedback-element-highlight"
          data-component={hoverHighlight.componentName || 'element'}
          style={{
            left: hoverHighlight.rect.left,
            top: hoverHighlight.rect.top,
            width: hoverHighlight.rect.width,
            height: hoverHighlight.rect.height,
          }}
        />
      )}

      {/* Location pin */}
      {locationContext && isOpen && (
        <div
          className="ui-feedback-pin"
          style={{ left: locationContext.clickX, top: locationContext.clickY }}
        >
          <PinIcon />
        </div>
      )}

      {/* Feedback Modal */}
      <FeedbackModal />

      {/* Tickets List Modal */}
      {showTickets && (
        <FeedbackList
          apiUrl={config.apiUrl}
          appName={config.appName}
          onClose={() => setShowTickets(false)}
        />
      )}
    </div>
  );
}

// Icons
function FeedbackIcon() {
  return (
    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
    </svg>
  );
}

function CloseIcon() {
  return (
    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <line x1="18" y1="6" x2="6" y2="18" />
      <line x1="6" y1="6" x2="18" y2="18" />
    </svg>
  );
}

function PinIcon() {
  return (
    <svg width="24" height="24" viewBox="0 0 24 24" fill="var(--feedback-primary)" stroke="white" strokeWidth="1.5">
      <path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z" />
      <circle cx="12" cy="10" r="3" fill="white" />
    </svg>
  );
}

function ListIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <line x1="8" y1="6" x2="21" y2="6" />
      <line x1="8" y1="12" x2="21" y2="12" />
      <line x1="8" y1="18" x2="21" y2="18" />
      <circle cx="4" cy="6" r="1" fill="currentColor" />
      <circle cx="4" cy="12" r="1" fill="currentColor" />
      <circle cx="4" cy="18" r="1" fill="currentColor" />
    </svg>
  );
}

function NoteIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
      <polyline points="14 2 14 8 20 8" />
      <line x1="16" y1="13" x2="8" y2="13" />
      <line x1="16" y1="17" x2="8" y2="17" />
    </svg>
  );
}

function PinSelectIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <circle cx="12" cy="10" r="3" />
      <path d="M12 2a8 8 0 0 0-8 8c0 5.4 8 12 8 12s8-6.6 8-12a8 8 0 0 0-8-8z" />
    </svg>
  );
}
