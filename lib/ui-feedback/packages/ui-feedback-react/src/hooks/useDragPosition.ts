/**
 * Hook for managing draggable widget positioning with localStorage persistence
 */

import { useCallback, useEffect, useRef, useState } from 'react';

const STORAGE_KEY = 'ui-feedback-position';
const BUTTON_SIZE = 60;
const MARGIN = 12;

interface DragStart {
  x: number;
  y: number;
  buttonX: number;
  buttonY: number;
}

type Position = { x: number; y: number };

export interface UseDragPositionResult {
  position: Position | null;
  isDragging: boolean;
  handleMouseDown: (e: React.MouseEvent) => void;
  buttonRef: React.RefObject<HTMLDivElement | null>;
}

function clampPosition(x: number, y: number): Position {
  const maxX = window.innerWidth - BUTTON_SIZE;
  const maxY = window.innerHeight - BUTTON_SIZE;
  return {
    x: Math.max(MARGIN, Math.min(maxX, x)),
    y: Math.max(MARGIN, Math.min(maxY, y)),
  };
}

function loadSavedPosition(): Position | null {
  const saved = localStorage.getItem(STORAGE_KEY);
  if (!saved) return null;
  try {
    return JSON.parse(saved);
  } catch {
    return null;
  }
}

function onDragMove(
  e: MouseEvent,
  dragStartRef: React.MutableRefObject<DragStart | null>,
  setIsDragging: (v: boolean) => void,
  setPosition: (pos: Position) => void,
): void {
  const start = dragStartRef.current;
  if (!start) return;
  const dx = Math.abs(e.clientX - start.x);
  const dy = Math.abs(e.clientY - start.y);
  if (dx > 5 || dy > 5) {
    setIsDragging(true);
    setPosition(clampPosition(start.buttonX + (e.clientX - start.x), start.buttonY + (e.clientY - start.y)));
  }
}

function onDragEnd(
  dragStartRef: React.MutableRefObject<DragStart | null>,
  setPosition: React.Dispatch<React.SetStateAction<Position | null>>,
  setIsDragging: (v: boolean) => void,
): void {
  if (!dragStartRef.current) return;
  setPosition((pos) => {
    if (pos) localStorage.setItem(STORAGE_KEY, JSON.stringify(pos));
    return pos;
  });
  dragStartRef.current = null;
  setTimeout(() => setIsDragging(false), 0);
}

export function useDragPosition(): UseDragPositionResult {
  const [position, setPosition] = useState<Position | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const dragStartRef = useRef<DragStart | null>(null);
  const buttonRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const saved = loadSavedPosition();
    if (saved) setPosition(saved);
  }, []);

  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    if (e.button !== 0) return;
    const rect = buttonRef.current?.getBoundingClientRect();
    if (!rect) return;
    dragStartRef.current = { x: e.clientX, y: e.clientY, buttonX: rect.left, buttonY: rect.top };
  }, []);

  useEffect(() => {
    const move = (e: MouseEvent) => onDragMove(e, dragStartRef, setIsDragging, setPosition);
    const up = () => onDragEnd(dragStartRef, setPosition, setIsDragging);
    document.addEventListener('mousemove', move);
    document.addEventListener('mouseup', up);
    return () => {
      document.removeEventListener('mousemove', move);
      document.removeEventListener('mouseup', up);
    };
  }, []);

  return { position, isDragging, handleMouseDown, buttonRef };
}
