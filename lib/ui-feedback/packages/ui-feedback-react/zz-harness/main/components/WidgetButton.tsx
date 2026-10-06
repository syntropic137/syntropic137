/**
 * Floating button + menu sub-component for FeedbackWidget
 */

import { CloseIcon, FeedbackIcon, ListIcon, NoteIcon, PinSelectIcon } from './icons';

export interface WidgetButtonProps {
  isFeedbackMode: boolean;
  isDragging: boolean;
  showMenu: boolean;
  openCount: number;
  onToggleMenu: () => void;
  onCloseFeedbackMode: () => void;
  onQuickNote: () => void;
  onPinToElement: () => void;
  onViewTickets: () => void;
  keyboardShortcut?: string;
}

export function WidgetButton({
  isFeedbackMode, isDragging, showMenu, openCount,
  onToggleMenu, onCloseFeedbackMode, onQuickNote, onPinToElement, onViewTickets, keyboardShortcut,
}: WidgetButtonProps) {
  if (isFeedbackMode) {
    return (
      <button type="button" className="ui-feedback-button-inner" onClick={() => !isDragging && onCloseFeedbackMode()} title="Cancel (Esc)">
        <CloseIcon size={24} />
      </button>
    );
  }

  return (
    <>
      <button type="button" className="ui-feedback-button-inner" onClick={() => !isDragging && onToggleMenu()} title={`Feedback (${keyboardShortcut})`}>
        <FeedbackIcon />
      </button>
      {openCount > 0 && <span className="ui-feedback-button-badge">{openCount}</span>}
      {showMenu && !isDragging && (
        <div className="ui-feedback-menu">
          <button className="ui-feedback-menu-item" onClick={onQuickNote}>
            <NoteIcon /> <span className="ui-feedback-menu-label">Quick Note</span> <kbd className="ui-feedback-menu-hotkey">{'\u2303\u21E7'}Q</kbd>
          </button>
          <button className="ui-feedback-menu-item" onClick={onPinToElement}>
            <PinSelectIcon /> <span className="ui-feedback-menu-label">Pin to Element</span> <kbd className="ui-feedback-menu-hotkey">{'\u2303\u21E7'}F</kbd>
          </button>
          <button className="ui-feedback-menu-item" onClick={onViewTickets}>
            <ListIcon /> <span className="ui-feedback-menu-label">View Tickets</span>
            {openCount > 0 && <span className="ui-feedback-menu-badge">{openCount}</span>}
            <kbd className="ui-feedback-menu-hotkey">{'\u2303\u21E7'}T</kbd>
          </button>
        </div>
      )}
    </>
  );
}
