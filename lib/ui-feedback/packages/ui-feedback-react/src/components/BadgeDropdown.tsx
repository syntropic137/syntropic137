/**
 * Generic badge-style dropdown for type/priority selection
 */

import { useState } from 'react';
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
}

export function BadgeDropdown({ options, value, onChange, className, onOpen }: BadgeDropdownProps) {
  const [isOpen, setIsOpen] = useState(false);
  const selected = options.find((o) => o.value === value);

  const handleToggle = () => {
    const next = !isOpen;
    setIsOpen(next);
    if (next) onOpen?.();
  };

  const handleSelect = (optionValue: string) => {
    onChange(optionValue);
    setIsOpen(false);
  };

  return (
    <div className="ui-feedback-badge-container">
      <button
        type="button"
        className={`ui-feedback-badge ${className || ''}`}
        style={{ backgroundColor: selected?.color }}
        onClick={handleToggle}
      >
        {selected?.emoji && <span>{selected.emoji}</span>}
        <span>{selected?.label || value}</span>
        <ChevronIcon />
      </button>
      {isOpen && (
        <div className="ui-feedback-badge-dropdown">
          {options.map((option) => (
            <button
              key={option.value}
              type="button"
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
