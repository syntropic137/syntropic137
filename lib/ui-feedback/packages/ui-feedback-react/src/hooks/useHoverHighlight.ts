/**
 * Hook for element hover highlighting in feedback mode
 */

import { useEffect, useState } from 'react';
import { getReactComponentName, getComponentInfo } from '../utils/getReactComponent';

const SKIP_TAGS = new Set(['HTML', 'BODY', 'MAIN', 'ARTICLE', 'SECTION', 'ASIDE', 'HEADER', 'FOOTER', 'NAV']);
const MIN_SIZE = 20;
const MAX_VIEWPORT_RATIO = 0.8;

export interface HoverHighlight {
  rect: DOMRect;
  componentName: string | null;
}

function findBestElement(x: number, y: number): HTMLElement | null {
  const elements = document.elementsFromPoint(x, y) as HTMLElement[];

  for (const el of elements) {
    if (el.closest('.ui-feedback-root')) continue;
    if (el.classList.contains('ui-feedback-mode-overlay')) continue;
    if (el.classList.contains('ui-feedback-mode-hint')) continue;
    if (el.classList.contains('ui-feedback-element-highlight')) continue;
    if (SKIP_TAGS.has(el.tagName)) continue;

    const rect = el.getBoundingClientRect();
    const viewportArea = window.innerWidth * window.innerHeight;
    if (rect.width * rect.height > viewportArea * MAX_VIEWPORT_RATIO) continue;
    if (rect.width < MIN_SIZE || rect.height < MIN_SIZE) continue;

    return el;
  }

  return null;
}

export function useHoverHighlight(isFeedbackMode: boolean): HoverHighlight | null {
  const [hoverHighlight, setHoverHighlight] = useState<HoverHighlight | null>(null);

  useEffect(() => {
    if (!isFeedbackMode) {
      setHoverHighlight(null);
      return;
    }

    const handleMouseMove = (e: MouseEvent) => {
      const target = findBestElement(e.clientX, e.clientY);

      if (!target) {
        setHoverHighlight(null);
        return;
      }

      const rect = target.getBoundingClientRect();
      const componentName = getReactComponentName(target) || getComponentInfo(target);
      setHoverHighlight({ rect, componentName });
    };

    const handleMouseLeave = () => setHoverHighlight(null);

    document.addEventListener('mousemove', handleMouseMove);
    document.addEventListener('mouseleave', handleMouseLeave);

    return () => {
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseleave', handleMouseLeave);
      setHoverHighlight(null);
    };
  }, [isFeedbackMode]);

  return hoverHighlight;
}
