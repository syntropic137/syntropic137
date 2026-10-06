/**
 * Area selection overlay for capturing screenshot regions
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import type { AreaBounds } from '../utils/captureArea';

export interface AreaSelectorProps {
  onCapture: (bounds: AreaBounds) => void;
  onCancel: () => void;
}

export function AreaSelector({ onCapture, onCancel }: AreaSelectorProps) {
  const [isSelecting, setIsSelecting] = useState(false);
  const [startPos, setStartPos] = useState({ x: 0, y: 0 });
  const [currentPos, setCurrentPos] = useState({ x: 0, y: 0 });
  const overlayRef = useRef<HTMLDivElement>(null);

  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    setIsSelecting(true);
    setStartPos({ x: e.clientX, y: e.clientY });
    setCurrentPos({ x: e.clientX, y: e.clientY });
  }, []);

  const handleMouseMove = useCallback(
    (e: React.MouseEvent) => {
      if (isSelecting) {
        setCurrentPos({ x: e.clientX, y: e.clientY });
      }
    },
    [isSelecting]
  );

  const handleMouseUp = useCallback(() => {
    if (isSelecting) {
      setIsSelecting(false);

      // Calculate bounds
      const x = Math.min(startPos.x, currentPos.x);
      const y = Math.min(startPos.y, currentPos.y);
      const width = Math.abs(currentPos.x - startPos.x);
      const height = Math.abs(currentPos.y - startPos.y);

      // Only capture if area is meaningful (> 10px in both dimensions)
      if (width > 10 && height > 10) {
        onCapture({ x, y, width, height });
      } else {
        onCancel();
      }
    }
  }, [isSelecting, startPos, currentPos, onCapture, onCancel]);

  // Handle escape key
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onCancel();
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [onCancel]);

  // Calculate selection rectangle
  const selectionStyle = isSelecting
    ? {
      left: Math.min(startPos.x, currentPos.x),
      top: Math.min(startPos.y, currentPos.y),
      width: Math.abs(currentPos.x - startPos.x),
      height: Math.abs(currentPos.y - startPos.y),
    }
    : null;

  return (
    <div
      ref={overlayRef}
      className="ui-feedback-area-overlay"
      onMouseDown={handleMouseDown}
      onMouseMove={handleMouseMove}
      onMouseUp={handleMouseUp}
      onMouseLeave={handleMouseUp}
    >
      {selectionStyle && (
        <div className="ui-feedback-area-selection" style={selectionStyle} />
      )}
      <div className="ui-feedback-area-hint">
        Click and drag to select an area • Press <kbd>Esc</kbd> to cancel
      </div>
    </div>
  );
}
