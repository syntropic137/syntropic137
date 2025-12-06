/**
 * Hook for capturing element information on click
 */

import { useCallback } from 'react';
import type { LocationContext } from '../types';
import { getCssSelector, getXPath } from '../utils/getElementPath';
import { getComponentInfo } from '../utils/getReactComponent';

export interface UseElementInfoResult {
  /**
   * Capture element info from a mouse event
   */
  captureFromEvent: (event: MouseEvent) => LocationContext;

  /**
   * Capture element info from an element directly
   */
  captureFromElement: (element: Element, x?: number, y?: number) => LocationContext;
}

/**
 * Hook for capturing location context from DOM elements
 */
export function useElementInfo(): UseElementInfoResult {
  const captureFromElement = useCallback(
    (element: Element, x?: number, y?: number): LocationContext => {
      const rect = element.getBoundingClientRect();

      return {
        url: window.location.href,
        route: getRouteFromUrl(),
        viewportWidth: window.innerWidth,
        viewportHeight: window.innerHeight,
        clickX: x ?? Math.round(rect.left + rect.width / 2),
        clickY: y ?? Math.round(rect.top + rect.height / 2),
        cssSelector: getCssSelector(element),
        xpath: getXPath(element),
        componentName: getComponentInfo(element) ?? undefined,
      };
    },
    []
  );

  const captureFromEvent = useCallback(
    (event: MouseEvent): LocationContext => {
      const element = event.target as Element;
      return captureFromElement(element, event.clientX, event.clientY);
    },
    [captureFromElement]
  );

  return {
    captureFromEvent,
    captureFromElement,
  };
}

/**
 * Try to extract the route path from the URL
 * Works with React Router and similar SPA routers
 */
function getRouteFromUrl(): string | undefined {
  // Check for hash routing
  if (window.location.hash.startsWith('#/')) {
    return window.location.hash.slice(1);
  }

  // Return pathname for regular routing
  return window.location.pathname;
}
