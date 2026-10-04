/**
 * Generic badge-style dropdown for type/priority selection
 *
 * Keyboard: an optional `hotkey` opens it from anywhere in the form (shown as a
 * kbd hint on the badge); once open, arrows move between options, Enter picks
 * one and Escape closes without changing anything.
 */

import { useEffect, useRef, useState } from 'react';
import { useFormHotkey } from '../hooks/useFormHotkey';
import { ChevronIcon } from './icons';

interface BadgeOption {
  value: string;
  label: string;
  color: string;
  emoji?: string;
}

interface BadgeDropdownProps {
  options: BadgeOption[];
  value: string;
  onChange: (value: string) => void;
  className?: string;
  onOpen?: () => void;
  /** Single key that opens this dropdown while focus is not in a text field. */
  hotkey?: string;
}

const STEP: Partial<Record<string, number>> = { ArrowDown: 1, ArrowUp: -1 };

function moveFocus(list: HTMLElement, step: number): void {
  const items = Array.from(list.querySelectorAll<HTMLButtonElement>('[role="option"]'));
  const current = items.findIndex((item) => item === document.activeElement);
  items[(current + step + items.length) % items.length]?.focus();
}

export function BadgeDropdown({ options, value, onChange, className, onOpen, hotkey }: BadgeDropdownProps) {
  const [isOpen, setIsOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const selected = options.find((o) => o.value === value);

  const open = () => {
    if (!isOpen) onOpen?.();
    setIsOpen(true);
  };

  const close = () => {
    setIsOpen(false);
    triggerRef.current?.focus();
  };

  useFormHotkey(hotkey, open);

  // Opening hands focus to the current option, so arrows and Enter act on the list straight away.
  useEffect(() => {
    if (isOpen) listRef.current?.querySelector<HTMLButtonElement>('[aria-selected="true"]')?.focus();
  }, [isOpen]);

  const handleSelect = (optionValue: string) => {
    onChange(optionValue);
    close();
  };

  const handleListKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    const step = STEP[e.key];
    if (step !== undefined && listRef.current) {
      e.preventDefault();
      moveFocus(listRef.current, step);
    } else if (e.key === 'Escape') {
      // Close the list, not the whole modal.
      e.stopPropagation();
      close();
    }
  };

  // Focus moving to another control (e.g. the other badge's hotkey) closes this one.
  const handleBlur = (e: React.FocusEvent<HTMLDivElement>) => {
    if (e.relatedTarget && !e.currentTarget.contains(e.relatedTarget)) setIsOpen(false);
  };

  return (
    <div className="ui-feedback-badge-container" onBlur={handleBlur}>
      <button
        ref={triggerRef}
        type="button"
        className={`ui-feedback-badge ${className || ''}`}
        style={{ backgroundColor: selected?.color }}
        onClick={() => (isOpen ? setIsOpen(false) : open())}
        aria-expanded={isOpen}
        aria-haspopup="listbox"
        aria-keyshortcuts={hotkey}
      >
        {hotkey && <kbd className="ui-feedback-badge-hotkey" aria-hidden="true">{hotkey}</kbd>}
        {selected?.emoji && <span>{selected.emoji}</span>}
        <span>{selected?.label || value}</span>
        <ChevronIcon />
      </button>
      {isOpen && (
        <div ref={listRef} className="ui-feedback-badge-dropdown" role="listbox" onKeyDown={handleListKeyDown}>
          {options.map((option) => (
            <button
              key={option.value}
              type="button"
              role="option"
              aria-selected={value === option.value}
              className={`ui-feedback-badge-option ${value === option.value ? 'ui-feedback-badge-option--active' : ''}`}
              style={option.emoji ? undefined : { '--badge-color': option.color } as React.CSSProperties}
              onClick={() => handleSelect(option.value)}
            >
              {option.emoji ? (
                <span>{option.emoji}</span>
              ) : (
                <span className="ui-feedback-priority-dot" style={{ backgroundColor: option.color }} />
              )}
              <span>{option.label}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
